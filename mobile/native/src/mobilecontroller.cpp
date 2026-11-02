#include "mobilecontroller.h"
#include "bundle_identity.h"
#include "ui_strings.h"
#include "state_strings.h"
#include <bb/data/JsonDataAccess>
#include <QDir>
#include <QFileInfo>
#include <QLocale>
#include <QRegExp>
#include <QUuid>
#include <QtNetwork/QNetworkRequest>
#include <QStringList>
#include <fcntl.h>
#include <unistd.h>

namespace {
const int MAX_RESPONSE = 512 * 1024;
const int MAX_METADATA = 64 * 1024;
const qint64 MAX_PACKAGE = 64 * 1024 * 1024;
const char *LATEST_URL = "https://bb10-volte.octoooo.com/mobile/latest.json";

QVariantMap parseObject(const QByteArray &data)
{
    bb::data::JsonDataAccess json;
    const QVariant value = json.loadFromBuffer(data);
    return !json.hasError() && value.type() == QVariant::Map ? value.toMap() : QVariantMap();
}

bool completed(const QString &state)
{
    return state == "complete" || state == "completed" || state == "succeeded" ||
           state == "done" || state == "failed" || state == "cancelled";
}

QString bounded(const QVariant &value, int length = 4096)
{
    return value.type() == QVariant::String ? value.toString().left(length) : QString();
}

bool newerVersion(const QString &candidate, const QString &current)
{
    const QRegExp pattern("^[0-9]+(\\.[0-9]+){2,3}$");
    if (!pattern.exactMatch(candidate) || !pattern.exactMatch(current)) return false;
    const QStringList left = candidate.split('.'), right = current.split('.');
    for (int i = 0; i < qMax(left.size(), right.size()); ++i) {
        const uint a = i < left.size() ? left.at(i).toUInt() : 0;
        const uint b = i < right.size() ? right.at(i).toUInt() : 0;
        if (a != b) return a > b;
    }
    return false;
}
}

MobileController::MobileController(QObject *parent)
    : QObject(parent), m_settings(), m_busy(false), m_timedOut(false), m_runtimeError(false),
      m_waitingForRoot(false), m_refreshLegacy(false),
      m_foreground(true), m_sleeping(false), m_experimentalVisible(false),
      m_pickerOpen(false), m_pickerClosed(false), m_pickerResultHandled(false), m_refreshPending(true), m_reconcilingCalls(false),
      m_network(this), m_reply(0), m_downloadBytes(0), m_redirects(0)
{
    m_language = m_settings.value("language", QLocale::system().name().startsWith("zh") ? "zh" : "en").toString();
    if (m_language != "zh") m_language = "en";
    m_backupLocation = m_settings.value("backup_location", sdAvailable() ? "sdcard" : "internal").toString();
    if (m_backupLocation != "sdcard" || !sdAvailable()) m_backupLocation = "internal";
    m_legacyProfile = m_settings.value("legacy_profile", "china-mobile").toString();
    if (!knownProfile(m_legacyProfile)) m_legacyProfile = "china-mobile";
    m_jobId = m_settings.value("pending_job").toString();
    if (!safeId(m_jobId)) m_jobId.clear();
    m_operationId = m_settings.value("pending_operation").toString();
    if (!QRegExp("^[a-f0-9]{32}$").exactMatch(m_operationId)) m_operationId.clear();
    m_operationAction = m_settings.value("pending_operation_action").toString();
    m_pendingCallContext = m_settings.value("pending_call_context").toString();
    if (m_operationId.isEmpty() || m_operationAction != "confirm-calls" ||
        !QRegExp("^[a-f0-9]{32}$").exactMatch(m_pendingCallContext)) {
        m_operationAction.clear();
        m_pendingCallContext.clear();
    } else {
        m_reconcilingCalls = true;
    }
    m_lastExportPath = m_settings.value("last_export_path").toString().left(2048);
    if (!m_lastExportPath.startsWith("/accounts/1000/shared/") &&
        !m_lastExportPath.startsWith("/accounts/1000/removable/sdcard/")) m_lastExportPath.clear();
    m_model.insert("state", "checking");
    connect(&m_process, SIGNAL(started()), this, SLOT(processStarted()));
    connect(&m_process, SIGNAL(readyReadStandardOutput()), this, SLOT(processOutput()));
    connect(&m_process, SIGNAL(readyReadStandardError()), this, SLOT(processErrorOutput()));
    connect(&m_process, SIGNAL(finished(int,QProcess::ExitStatus)), this, SLOT(processFinished(int,QProcess::ExitStatus)));
    connect(&m_process, SIGNAL(error(QProcess::ProcessError)), this, SLOT(processError(QProcess::ProcessError)));
    m_deadline.setSingleShot(true);
    connect(&m_deadline, SIGNAL(timeout()), this, SLOT(processTimeout()));
    m_pollTimer.setSingleShot(true);
    connect(&m_pollTimer, SIGNAL(timeout()), this, SLOT(poll()));
    m_networkDeadline.setSingleShot(true);
    connect(&m_networkDeadline, SIGNAL(timeout()), this, SLOT(networkTimeout()));
}

void MobileController::initialize()
{
    // isFullscreen() is false until the first Navigator event. Keep the first
    // launch observation, then use the actual application lifecycle signals.
    connect(parent(), SIGNAL(fullscreen()), this, SLOT(enteredForeground()));
    connect(parent(), SIGNAL(thumbnail()), this, SLOT(enteredBackground()));
    connect(parent(), SIGNAL(invisible()), this, SLOT(enteredBackground()));
    connect(parent(), SIGNAL(asleep()), this, SLOT(screenAsleep()));
    connect(parent(), SIGNAL(awake()), this, SLOT(screenAwake()));
    scheduleRefresh();
}

bool MobileController::refreshBlocked() const
{
    return !m_foreground || m_sleeping || m_busy || m_pickerOpen || !m_pendingAction.isEmpty();
}

void MobileController::scheduleRefresh()
{
    m_pollTimer.stop();
    if (refreshBlocked()) return;
    if (m_experimentalVisible && m_jobId.isEmpty() && !m_refreshLegacy && !m_waitingForRoot) return;
    const QString state = m_model.value("state").toString();
    if (m_refreshPending || m_refreshLegacy) m_pollTimer.start(200);
    else if (m_waitingForRoot) m_pollTimer.start(10000);
    else if (m_jobId.isEmpty() && !m_refreshLegacy && (state == "experimental" || state == "exported")) return;
    else if (!m_error.isEmpty()) return;
    else if (jobRunning()) m_pollTimer.start(1800);
    else if (m_model.value("job").toMap().value("state").toString() == "waiting_reboot") m_pollTimer.start(25000);
    else if (state == "waiting" || state == "waiting_ims" || state == "waiting_ims_apn") m_pollTimer.start(10000);
}

void MobileController::enteredForeground()
{
    m_foreground = true;
    m_refreshPending = true;
    scheduleRefresh();
}

void MobileController::enteredBackground()
{
    m_foreground = false;
    m_pollTimer.stop();
}

void MobileController::screenAsleep()
{
    m_sleeping = true;
    m_pollTimer.stop();
}

void MobileController::screenAwake()
{
    m_sleeping = false;
    if (m_foreground) m_refreshPending = true;
    scheduleRefresh();
}

void MobileController::setExperimentalVisible(bool visible)
{
    if (m_experimentalVisible == visible) return;
    m_experimentalVisible = visible;
    if (!visible) {
        m_refreshPending = true;
    }
    scheduleRefresh();
}

QString MobileController::label(const QString &key) const
{
    for (int i = 0; UI_STRINGS[i].key; ++i)
        if (key == QLatin1String(UI_STRINGS[i].key))
            return QString::fromUtf8(m_language == "zh" ? UI_STRINGS[i].zh : UI_STRINGS[i].en);
    return QString();
}

void MobileController::setLanguage(const QString &value)
{
    if ((value != "zh" && value != "en") || value == m_language) return;
    m_language = value;
    m_settings.setValue("language", value);
    m_settings.sync();
    // Language is presentation only. In-flight, failed and experimental
    // results are translated in place without scheduling another operation.
    emit languageChanged();
    emit modelChanged();
    emit settingsChanged();
}

QString MobileController::display(const QString &key, const QString &code) const
{
    const QString localized = bounded(m_model.value("display_i18n").toMap().value(m_language).toMap().value(key));
    if (!localized.isEmpty()) return localized;
    // A response may arrive after the user changes language. Never label that
    // response using the language selected after its request was sent.
    const QString supplied = bounded(m_model.value("display").toMap().value(key));
    if (m_modelLanguage == m_language && !supplied.isEmpty()) return supplied;
    const int field = key == "title" ? 0 : key == "message" ? 1 : key == "primary_label" ? 2 : -1;
    const QString state = bounded(m_model.value("state"), 80);
    if (field >= 0) {
        for (int i = 0; UI_STATE_STRINGS[i].state; ++i)
            if (state == QLatin1String(UI_STATE_STRINGS[i].state))
                return QString::fromUtf8(m_language == "zh" ? UI_STATE_STRINGS[i].zh[field] : UI_STATE_STRINGS[i].en[field]);
    }
    const QString local = label(bounded(m_model.value(code), 100));
    if (!local.isEmpty()) return local;
    if (key == "message" && state != "checking") return label("state_unrecognized_help");
    if (key == "title" && state != "checking") return label("state_unrecognized");
    return QString();
}

QString MobileController::statusTitle() const
{
    if (m_waitingForRoot) return label("state_waiting_root");
    if (callConfirmationInProgress()) return label(m_reconcilingCalls ? "calls_rechecking" : "calls_saving");
    if (!m_error.isEmpty()) {
        if (m_runtimeError && !display("title", "title_code").isEmpty()) return display("title", "title_code");
        const QString local = label(m_error);
        return local.isEmpty() ? label("operation_failed") : local;
    }
    const QString supplied = display("title", "title_code");
    if (!supplied.isEmpty()) return supplied;
    const QString state = label("state_" + bounded(m_model.value("state"), 80));
    return state.isEmpty() ? label("checking") : state;
}

QString MobileController::statusMessage() const
{
    if (m_waitingForRoot) return label("root_waiting_help");
    if (callConfirmationInProgress()) return label(m_reconcilingCalls ? "calls_rechecking_help" : "calls_saving_help");
    if (m_runtimeError && !display("message", "message_code").isEmpty()) return display("message", "message_code");
    if (m_error == "root_not_ready") return label("root_help");
    if (!m_error.isEmpty()) return label("inspect");
    return display("message", "message_code");
}

QString MobileController::primaryAction() const
{
    const QString action = bounded(m_model.value("primary_action"), 64);
    if (!m_error.isEmpty() && !(m_runtimeError && action == "resume" && !m_jobId.isEmpty() && allowed(action))) return "inspect";
    // Experimental actions are intentionally never promoted to the home button.
    if (!knownAction(action) || action.startsWith("legacy-") || (action == "poll" && m_jobId.isEmpty())) return "inspect";
    return action;
}

QString MobileController::primaryText() const
{
    if (primaryAction() == "resume" || primaryAction() == "poll") return label(primaryAction());
    if (m_error.isEmpty() || (m_runtimeError && primaryAction() == "resume")) {
        const QString supplied = display("primary_label", "primary_action");
        if (!supplied.isEmpty() && !bounded(m_model.value("primary_action")).startsWith("legacy-")) return supplied;
    }
    const QString local = label(primaryAction());
    return local.isEmpty() ? label("inspect") : local;
}

QString MobileController::deviceText() const
{
    const QVariantMap details = m_model.value("details").toMap();
    const QVariant device = details.value("device", details.value("variant"));
    const QString value = device.type() == QVariant::Map ? bounded(device.toMap().value("variant"), 120) : bounded(device, 120);
    return value.isEmpty() || value == "unknown" ? label("unknown") : value;
}

QString MobileController::carrierText() const
{
    const QString value = bounded(m_model.value("details").toMap().value("carrier"), 120);
    const QString translated = label("carrier_" + value);
    return translated.isEmpty() ? label("carrier_unknown") : translated;
}

QString MobileController::detailText() const
{
    QVariantMap details = m_model.value("details").toMap();
    const QVariantMap device = details.value("device").toMap();
    for (QVariantMap::const_iterator i = device.begin(); i != device.end(); ++i)
        if (i.key() == "variant" || i.key() == "os_version" || i.key() == "board_type") details.insert(i.key(), i.value());
    QStringList rows;
    for (QVariantMap::const_iterator i = details.begin(); i != details.end(); ++i) {
        if (i.value().type() != QVariant::String && i.value().type() != QVariant::Bool &&
            i.value().type() != QVariant::Int && i.value().type() != QVariant::UInt &&
            i.value().type() != QVariant::LongLong && i.value().type() != QVariant::ULongLong) continue;
        const QString name = label(i.key());
        if (name.isEmpty() || i.key() == "ok") continue;
        QString value = i.value().toString().left(2048);
        if (i.value().type() == QVariant::Bool) value = label(i.value().toBool() ? "yes" : "no");
        else if (i.key() == "carrier") value = carrierText();
        else if (value == "unknown") value = label("unknown");
        else if (i.key() == "phase") value = label("phase_" + value);
        else if (i.key() == "error_code") {
            value = label(value);
            if (value.isEmpty()) value = label("check_unknown");
        }
        else if (i.key() == "support" || i.key() == "hardware_validation" || i.key() == "outcome") value = label(value);
        if (value.isEmpty()) value = label("value_unrecognized");
        rows.append(name + ": " + value);
    }
    const QVariantList checks = details.value("checks").toList();
    for (int i = 0; i < checks.size() && i < 64; ++i) {
        const QVariantMap check = checks.at(i).toMap();
        if (check.value("status").toString() == "pass") continue;
        const QString code = bounded(check.value("code"), 80);
        if (!QRegExp("^[a-z0-9_]{1,80}$").exactMatch(code)) continue;
        const QString translated = label("check_" + code);
        rows.append(label("check_needed") + ": " + (translated.isEmpty() ? label("check_unknown") : translated));
    }
    if (!m_error.isEmpty()) {
        const QString reason = label(m_error);
        rows.append(reason.isEmpty() ? label("check_unknown") : reason);
    }
    if (!m_lastExportPath.isEmpty() && !details.contains("export_path") && !details.contains("path")) rows.append(label("export_path") + ": " + m_lastExportPath);
    return rows.join("\n\n");
}

QString MobileController::jobText() const
{
    const QVariantMap job = m_model.value("job").toMap();
    const QString state = bounded(job.value("state"), 80);
    if (state == "interrupted") return label("job_interrupted");
    if (state == "failed") return label("job_failed");
    const QString phase = label("phase_" + bounded(job.value("phase"), 80));
    if (!phase.isEmpty()) return phase;
    if (jobRunning()) return label("job_running");
    return m_jobId.isEmpty() ? QString() : label("job_pending");
}

QString MobileController::notice() const { return label(m_notice); }
QString MobileController::version() const { return QLatin1String(BB10_MOBILE_VERSION); }
QString MobileController::packageName() const { return m_packagePath.isEmpty() ? label("no_package") : QFileInfo(m_packagePath).fileName(); }
bool MobileController::sdAvailable() const { return QFileInfo("/accounts/1000/removable/sdcard").isDir(); }

void MobileController::setBackupLocation(const QString &value)
{
    if (m_busy || jobRunning() || (value != "internal" && value != "sdcard") ||
        (value == "sdcard" && !sdAvailable())) return;
    m_backupLocation = value;
    m_settings.setValue("backup_location", value);
    emit settingsChanged();
}

void MobileController::setLegacyProfile(const QString &value)
{
    if (m_busy || jobRunning() || !knownProfile(value) || value == m_legacyProfile) return;
    m_legacyProfile = value;
    m_checkedLegacyProfile.clear();
    m_settings.setValue("legacy_profile", value);
    emit settingsChanged();
    emit modelChanged();
}

bool MobileController::jobRunning() const
{
    const QString state = m_model.value("job").toMap().value("state").toString();
    return state == "queued" || state == "running" || state == "pending" || state == "starting";
}

bool MobileController::operationInProgress() const
{
    // A failed observation must reveal its recovery UI rather than leave a
    // modal spinner over stale job data. Reboot/network waits are not jobs.
    if (!m_error.isEmpty()) return false;
    const QStringList changes = QString("install,enable,disable,update,rollback,uninstall,legacy-install,legacy-start,legacy-stop,legacy-update,legacy-uninstall").split(',');
    const QString jobAction = m_model.value("job").toMap().value("action").toString();
    return callConfirmationInProgress() ||
           (m_busy && (changes.contains(m_action) || (m_action == "resume" && changes.contains(jobAction)))) ||
           (jobRunning() && changes.contains(jobAction));
}

bool MobileController::callConfirmationInProgress() const
{
    return (m_busy && m_action == "confirm-calls") ||
           (m_reconcilingCalls && (m_busy || m_refreshPending));
}

bool MobileController::knownAction(const QString &action)
{
    const QStringList actions = QString("inspect,status,poll,install,enable,disable,update,rollback,uninstall,export,compatibility,confirm-calls,resume,legacy-inspect,legacy-install,legacy-start,legacy-stop,legacy-update,legacy-uninstall").split(',');
    return actions.contains(action);
}

bool MobileController::readAction(const QString &action)
{
    return action == "inspect" || action == "status" || action == "poll" || action == "legacy-inspect";
}

bool MobileController::safeId(const QString &value)
{
    return QRegExp("^[A-Za-z0-9_.-]{1,96}$").exactMatch(value) && value != "." && value != "..";
}

bool MobileController::knownProfile(const QString &value)
{
    if (QString("china-mobile,china-unicom,china-telecom,china-telecom-46011").split(',').contains(value)) return true;
    // This catalog only selects a UI option. The root worker independently
    // verifies the signed catalog, exact profile and every hardware gate.
    QFile input(QDir::current().absoluteFilePath("app/native/assets/materials/variant-trials.json"));
    if (!input.open(QIODevice::ReadOnly) || input.size() > 65536) return false;
    const QVariantList cases = parseObject(input.readAll()).value("cases").toList();
    for (int i = 0; i < cases.size() && i < 32; ++i)
        if (cases.at(i).toMap().value("profile_id").toString() == value) return true;
    return false;
}

bool MobileController::allowed(const QString &action) const
{
    if (!knownAction(action) || m_busy) return false;
    if (readAction(action)) return true;
    if (jobRunning()) return false;
    if (action.startsWith("legacy-") && m_checkedLegacyProfile != m_legacyProfile) return false;
    if (action == "compatibility") return true;
    if (!m_error.isEmpty() && !m_runtimeError) return false;
    const QVariantList actions = m_model.value("actions").toList();
    for (int i = 0; i < actions.size(); ++i) if (actions.at(i).toString() == action) return true;
    return false;
}

QString MobileController::shellQuote(const QString &value)
{
    QString result(value);
    result.replace("'", "'\\''");
    return "'" + result + "'";
}

QString MobileController::newOperationId() const
{
    QString id = QUuid::createUuid().toString();
    return id.remove('{').remove('}').remove('-').toLower();
}

bool MobileController::verifyEntry(QByteArray *bytes, QString *bundlePath)
{
    const QString expected = QLatin1String(BB10_ENTRY_SHA256);
    if (!QRegExp("^[a-f0-9]{64}$").exactMatch(expected)) { fail("bundle_missing"); return false; }
    const QFileInfo info(QDir::current().absoluteFilePath("app/native/assets/runtime/entry.py"));
    if (!info.isFile() || info.isSymLink() || info.size() < 1 || info.size() > 1024 * 1024) { fail("bundle_changed"); return false; }
    QFile file(info.absoluteFilePath());
    if (!file.open(QIODevice::ReadOnly)) { fail("bundle_changed"); return false; }
    const QByteArray data = file.readAll();
    // A quoted heredoc preserves every verified byte only with a final LF.
    if (data.size() < 1 || data.size() > 1024 * 1024 || !data.endsWith('\n') || data.contains('\0')) {
        fail("bundle_changed"); return false;
    }
    unsigned char digest[SHA256_DIGEST_LENGTH];
    SHA256(reinterpret_cast<const unsigned char *>(data.constData()), data.size(), digest);
    if (QString::fromLatin1(QByteArray(reinterpret_cast<const char *>(digest), SHA256_DIGEST_LENGTH).toHex()) != expected) {
        fail("bundle_changed"); return false;
    }
    *bytes = data;
    *bundlePath = QDir::current().absoluteFilePath("app/native/assets");
    if (bundlePath->contains('\n') || bundlePath->contains('\r') || bundlePath->contains(QChar(0))) { fail("bundle_changed"); return false; }
    return true;
}

void MobileController::fail(const QString &code)
{
    m_runtimeError = false;
    m_waitingForRoot = code == "root_not_ready" || code == "root_required";
    m_error = QRegExp("^[a-z0-9_-]{1,80}$").exactMatch(code) ? code : "operation_failed";
    emit modelChanged();
}

void MobileController::invoke(const QString &action, const QVariantMap &extra)
{
    if (!allowed(action) || m_process.state() != QProcess::NotRunning) { fail("action_unavailable"); return; }
    m_pollTimer.stop();
    QByteArray entryBytes;
    QString bundlePath;
    if (!verifyEntry(&entryBytes, &bundlePath)) return;
    if (!QFileInfo("/bin/__root").isExecutable()) {
        fail("root_not_ready");
        scheduleRefresh();
        return;
    }
    if (action.startsWith("legacy-") && (!knownProfile(extra.value("profile_id").toString()) ||
        extra.value("profile_id").toString() != m_legacyProfile)) { fail("action_unavailable"); return; }
    QVariantMap request(extra);
    request.insert("schema", 2);
    request.insert("language", m_language);
    m_requestLanguage = m_language;
    request.insert("backup_location", m_backupLocation);
    if (!m_packagePath.isEmpty() && action == "update") request.insert("package_path", m_packagePath);
    if (!m_jobId.isEmpty() && (action == "poll" || action == "resume" || action == "inspect" || action == "status")) request.insert("job_id", m_jobId);
    if (!readAction(action)) {
        m_operationId = newOperationId();
        m_operationAction = action;
        m_pendingCallContext = action == "confirm-calls" ? extra.value("call_context").toString() : QString();
        m_reconcilingCalls = false;
        m_settings.setValue("pending_operation", m_operationId);
        m_settings.setValue("pending_operation_action", m_operationAction);
        m_settings.setValue("pending_call_context", m_pendingCallContext);
        m_settings.sync();
    }
    if (!m_operationId.isEmpty()) request.insert("operation_id", m_operationId);
    bb::data::JsonDataAccess json;
    QByteArray payload;
    json.saveToBuffer(request, &payload);
    if (json.hasError() || payload.size() > 16384) { fail("invalid_response"); return; }
    m_action = action;
    m_requestedLegacyProfile = action == "legacy-inspect" ? extra.value("profile_id").toString() : QString();
    m_output.clear();
    m_timedOut = false;
    m_runtimeError = false;
    m_error.clear();
    m_notice.clear();
    m_busy = true;
    // The app-writable source is never reopened for Root execution. The bytes
    // checked above are copied through a literal heredoc into an exclusive,
    // Root-private directory. The source bundle is passed only as data.
    const QString privateDir = "/var/bb10_mobile_entry_" + newOperationId();
    const QString privateEntry = privateDir + "/entry.py";
    QByteArray boundary;
    do { boundary = ("BB10_ENTRY_" + newOperationId()).toLatin1(); } while (entryBytes.contains(boundary));
    const QString cleanup = "/usr/bin/python3.2 -B " + shellQuote(privateEntry) + " --cleanup";
    m_command = QString("unset PYTHONOPTIMIZE PYTHONINSPECT PYTHONSTARTUP PYTHONUSERBASE PYTHONPATH PYTHONHOME LD_PRELOAD ENV BASH_ENV\n"
        "export PATH=/proc/boot:/bin:/usr/bin:/base/bin:/base/usr/bin\n"
        "export LD_LIBRARY_PATH=/base/usr/lib:/base/lib:/base/lib/dll:/radio/lib:/radio/lib/dll:/radio/usr/lib:/proc/boot\n"
        "export PYTHONDONTWRITEBYTECODE=1 PYTHONHOME=/usr PYTHONPATH=/usr/lib/python32.zip:/usr/lib/python3.2/lib-dynload\n"
        "umask 077\n"
        "mkdir -m 700 " + shellQuote(privateDir) + " || exit 73\n"
        "trap " + shellQuote(cleanup) + " 0\n"
        "cat > " + shellQuote(privateEntry) + " <<'" + QString::fromLatin1(boundary) + "'\n").toUtf8();
    m_command.append(entryBytes);
    m_command.append(boundary);
    m_command.append(QString("\nif [ $? -ne 0 ]; then exit 74; fi\n"
        "/proc/boot/pathtrust " + shellQuote("!" + privateEntry) + " && /usr/bin/python3.2 -B " +
        shellQuote(privateEntry) + " " + shellQuote(action) + " " + shellQuote(QString::fromLatin1(payload.toBase64())) +
        " " + shellQuote(bundlePath) + "\nexit $?\n").toUtf8());
    QStringList environment;
    environment << "PATH=/proc/boot:/bin:/usr/bin:/base/bin:/base/usr/bin"
                << "LD_LIBRARY_PATH=/base/usr/lib:/base/lib:/base/lib/dll:/radio/lib:/radio/lib/dll:/radio/usr/lib:/proc/boot"
                << "LANG=C" << "TERM=dumb";
    m_process.setEnvironment(environment);
    m_process.setProcessChannelMode(QProcess::SeparateChannels);
    m_deadline.start(30000);
    m_process.start("/bin/__root", QStringList(), QIODevice::ReadWrite);
    emit modelChanged();
}

void MobileController::processStarted()
{
    m_process.write(m_command);
    m_process.closeWriteChannel();
    m_command.clear();
}

void MobileController::processOutput()
{
    m_output += m_process.readAllStandardOutput();
    if (m_output.size() > MAX_RESPONSE) { m_timedOut = true; m_process.kill(); fail("invalid_response"); }
}

void MobileController::processErrorOutput()
{
    // Root diagnostics can contain device identifiers. Never display or persist raw stderr.
    m_process.readAllStandardError();
}

void MobileController::processError(QProcess::ProcessError error)
{
    if (error != QProcess::FailedToStart) return;
    m_deadline.stop();
    m_busy = false;
    m_reconcilingCalls = false;
    m_action.clear();
    fail("root_not_ready");
    scheduleRefresh();
}

void MobileController::processTimeout()
{
    m_timedOut = true;
    if (m_action == "confirm-calls") reconcileCallConfirmation();
    else {
        m_reconcilingCalls = false;
        fail(readAction(m_action) ? "request_timeout" : "operation_unknown");
    }
    m_process.kill();
}

void MobileController::clearPendingOperation()
{
    m_operationId.clear();
    m_operationAction.clear();
    m_pendingCallContext.clear();
    m_settings.remove("pending_operation");
    m_settings.remove("pending_operation_action");
    m_settings.remove("pending_call_context");
}

bool MobileController::confirmedCallResponse(const QVariantMap &response) const
{
    return m_operationAction == "confirm-calls" && !m_operationId.isEmpty() &&
           !m_pendingCallContext.isEmpty() && response.value("schema").toInt() == 2 &&
           response.value("ok").type() == QVariant::Bool && response.value("ok").toBool() &&
           response.value("state").toString() == "verified" &&
           response.value("call_context").toString() == m_pendingCallContext;
}

void MobileController::reconcileCallConfirmation()
{
    // This schedules one read, never a repeated confirmation or device write.
    // The matching operation type/context also survive closing the app.
    if (m_operationAction != "confirm-calls" || m_pendingCallContext.isEmpty()) {
        fail("operation_unknown");
        return;
    }
    m_reconcilingCalls = true;
    m_refreshPending = true;
    m_runtimeError = false;
    m_error.clear();
    emit modelChanged();
}

void MobileController::processFinished(int code, QProcess::ExitStatus status)
{
    m_deadline.stop();
    processOutput();
    processErrorOutput();
    m_busy = false;
    QVariantMap response = parseObject(m_output.trimmed());
    if (response.isEmpty()) {
        // Some Root shells print a greeting. Only accept a complete JSON response line.
        const QList<QByteArray> lines = m_output.split('\n');
        for (int i = lines.size() - 1; i >= 0 && response.isEmpty(); --i)
            if (lines.at(i).trimmed().startsWith('{')) response = parseObject(lines.at(i).trimmed());
    }
    m_output.clear();
    if (m_timedOut) {
        // A complete matching ACK remains useful if the Root shell's cleanup
        // finishes late. Otherwise only a fresh read may resolve the result.
        if (m_action == "confirm-calls" && confirmedCallResponse(response)) {
            m_error.clear();
            acceptResponse(response);
            m_reconcilingCalls = false;
            m_refreshPending = false;
        } else if (m_action == "confirm-calls") {
            reconcileCallConfirmation();
        } else {
            m_reconcilingCalls = false;
        }
        m_action.clear();
        scheduleRefresh();
        emit modelChanged();
        return;
    }
    if (response.isEmpty()) {
        if (m_action == "confirm-calls") reconcileCallConfirmation();
        else {
            m_reconcilingCalls = false;
            fail(!readAction(m_action) ? "operation_unknown" :
                 (code != 0 || status != QProcess::NormalExit ? "root_not_ready" : "invalid_response"));
        }
    } else if (response.value("schema").toInt() != 2) {
        m_reconcilingCalls = false;
        fail("protocol_mismatch");
    } else {
        acceptResponse(response);
        m_reconcilingCalls = false;
    }
    m_action.clear();
    scheduleRefresh();
    emit modelChanged();
}

void MobileController::acceptResponse(const QVariantMap &response)
{
    m_model = response;
    m_modelLanguage = m_requestLanguage;
    const QVariantMap error = response.value("error").toMap();
    QVariantMap job = response.value("job").toMap();
    m_runtimeError = response.value("ok").type() == QVariant::Bool && !response.value("ok").toBool();
    if (m_runtimeError) {
        m_error = bounded(error.value("code", job.value("error_code")), 80);
        if (m_error.isEmpty()) m_error = "operation_failed";
    }
    m_waitingForRoot = m_runtimeError && (m_error == "root_not_ready" || m_error == "root_required");
    if (m_action == "legacy-inspect" && !m_runtimeError) m_checkedLegacyProfile = m_requestedLegacyProfile;
    else m_checkedLegacyProfile.clear();
    const QVariantMap details = response.value("details").toMap();
    const QVariantMap result = job.value("result").toMap();
    const QString exported = bounded(details.value("export_path", details.value("path",
        result.value("export_path", result.value("path")))), 2048);
    if (exported.startsWith("/accounts/1000/shared/") || exported.startsWith("/accounts/1000/removable/sdcard/")) {
        m_lastExportPath = exported;
        m_settings.setValue("last_export_path", exported);
    }
    const QString id = bounded(response.value("job_id", job.value("id")), 96);
    if (safeId(id)) {
        m_jobId = id;
        m_settings.setValue("pending_job", id);
        if (job.value("state").toString().isEmpty()) {
            job.insert("id", id);
            job.insert("state", "queued");
            m_model.insert("job", job);
        }
    }
    const bool recoverable = response.value("primary_action").toString() == "resume" &&
                             response.value("actions").toList().contains(QVariant("resume"));
    if (!m_jobId.isEmpty() && completed(job.value("state").toString()) && !recoverable) {
        const bool followUp = m_action != "inspect" && m_action != "status" && !response.value("live_status").toBool();
        m_refreshLegacy = bounded(job.value("action"), 64).startsWith("legacy-");
        if (job.value("state").toString() == "completed" && job.value("action").toString() == "update") {
            m_packagePath.clear();
            m_update.clear();
        }
        m_jobId.clear();
        if (m_operationAction != "confirm-calls" || confirmedCallResponse(response)) clearPendingOperation();
        m_settings.remove("pending_job");
        if (followUp) m_refreshPending = true;
    } else if (id.isEmpty() && !readAction(m_action) && !m_runtimeError &&
               (m_action != "confirm-calls" || confirmedCallResponse(response))) {
        // Call confirmation and read-only exports can return without a job.
        clearPendingOperation();
    } else if (id.isEmpty() && readAction(m_action) && confirmedCallResponse(response)) {
        // An observation may resolve this one saved call check. It must not
        // erase an unknown install/enable/update operation or another context.
        clearPendingOperation();
    }
    m_settings.sync();
    emit settingsChanged();
}

void MobileController::refresh()
{
    if (!m_busy && !m_pickerOpen && m_pendingAction.isEmpty()) {
        m_refreshPending = false;
        invoke("inspect");
    }
}

void MobileController::poll()
{
    if (refreshBlocked()) return;
    m_refreshPending = false;
    if (m_jobId.isEmpty() && (m_refreshLegacy || (m_waitingForRoot && m_experimentalVisible))) {
        m_refreshLegacy = false;
        legacyAction("legacy-inspect", m_legacyProfile);
        return;
    }
    invoke(m_jobId.isEmpty() ? "inspect" : "poll");
}

void MobileController::primary()
{
    if (primaryAction() == "update") applyBundledUpdate();
    else requestAction(primaryAction());
}

void MobileController::applyBundledUpdate()
{
    if (!canApplyBundledUpdate() || !allowed("update")) { fail("action_unavailable"); return; }
    m_packagePath.clear();
    emit settingsChanged();
    requestAction("update");
}

void MobileController::requestAction(const QString &action)
{
    if (!allowed(action)) { fail("action_unavailable"); return; }
    if (action == "update" && !hasPackage() && !canApplyBundledUpdate()) { fail("package_invalid"); return; }
    if (action == "resume" && m_jobId.isEmpty()) { fail("operation_unknown"); return; }
    if (action == "confirm-calls" || action.startsWith("legacy-")) { fail("action_unavailable"); return; }
    if (readAction(action) || action == "export" || action == "compatibility" || action == "resume") { invoke(action); return; }
    m_pendingAction = action;
    m_pendingExtra.clear();
    m_pollTimer.stop();
    emit confirmationNeeded();
}

QString MobileController::confirmationTitle() const
{
    const QString title = label(m_pendingAction == "download-update" ? "download_update" : m_pendingAction);
    return title.isEmpty() ? label("confirm_title") : title;
}

QString MobileController::confirmationBody() const
{
    QString text = label(m_pendingAction.startsWith("legacy-") ? "legacy_confirm" :
                         m_pendingAction == "download-update" ? "update_confirm" : m_pendingAction + "_confirm");
    if (m_pendingAction == "install" || m_pendingAction == "legacy-install")
        text += "\n\n" + label("backup_title") + ": " + label(m_backupLocation == "sdcard" ? "backup_sd" : "backup_internal") +
                "\n" + label(m_backupLocation == "sdcard" ? "backup_sd_note" : "backup_internal_note");
    return text;
}

void MobileController::confirmAction()
{
    const QString action = m_pendingAction;
    const QVariantMap extra = m_pendingExtra;
    cancelConfirmation();
    if (action == "download-update") { beginDownload(); return; }
    invoke(action, extra);
}

void MobileController::cancelConfirmation()
{
    m_pendingAction.clear();
    m_pendingExtra.clear();
    scheduleRefresh();
}

void MobileController::confirmCalls(bool outgoing, bool incoming, bool audio, bool lte, const QString &context)
{
    if (!outgoing || !incoming || !audio || !lte) { fail("calls_required"); return; }
    if (!QRegExp("^[a-f0-9]{32}$").exactMatch(context) || context != m_model.value("call_context").toString()) {
        fail("calls_context_changed"); return;
    }
    QVariantMap extra;
    extra.insert("outgoing", true); extra.insert("incoming", true); extra.insert("audio", true); extra.insert("lte", true);
    extra.insert("confirmed", true);
    extra.insert("call_context", context);
    invoke("confirm-calls", extra);
}

void MobileController::exportBackup()
{
    QVariantMap extra;
    extra.insert("export_kind", "backup");
    invoke("export", extra);
}

void MobileController::legacyAction(const QString &action, const QString &profileId)
{
    if (!action.startsWith("legacy-") || !knownAction(action) || jobRunning() ||
        !knownProfile(profileId) || profileId != m_legacyProfile) { fail("action_unavailable"); return; }
    QVariantMap extra;
    extra.insert("profile_id", profileId);
    extra.insert("experimental", true);
    if (action == "legacy-inspect") { invoke(action, extra); return; }
    if (!allowed(action)) { fail("action_unavailable"); return; }
    m_pendingAction = action;
    m_pendingExtra = extra;
    m_pollTimer.stop();
    emit confirmationNeeded();
}

bool MobileController::beginPackageSelection()
{
    if (m_busy || jobRunning() || !m_pendingAction.isEmpty()) return false;
    m_pickerOpen = true;
    m_pickerClosed = false;
    m_pickerResultHandled = false;
    m_pollTimer.stop();
    return true;
}

void MobileController::endPackageSelection()
{
    m_pickerResultHandled = true;
    if (m_pickerClosed) m_pickerOpen = false;
    scheduleRefresh();
}

void MobileController::packagePickerClosed()
{
    m_pickerClosed = true;
    if (m_pickerResultHandled) m_pickerOpen = false;
    scheduleRefresh();
}

void MobileController::packagePickerError()
{
    m_pickerClosed = true;
    endPackageSelection();
}

void MobileController::choosePackage(const QString &path)
{
    if (m_busy || jobRunning()) return;
    QString local = path.startsWith("file://") ? QUrl(path).toLocalFile() : path;
    QFileInfo info(local);
    const QString canonical = info.canonicalFilePath();
    if (!info.isFile() || info.isSymLink() || canonical.isEmpty() ||
        !(canonical.startsWith("/accounts/1000/shared/downloads/") || canonical.startsWith("/accounts/1000/removable/sdcard/")) ||
        info.suffix().toLower() != "zip" || info.size() <= 0 || info.size() > MAX_PACKAGE ||
        canonical.contains('\n') || canonical.contains('\r')) { fail("package_invalid"); return; }
    m_packagePath = canonical;
    m_notice = "package_selected";
    m_error.clear();
    emit settingsChanged();
    emit modelChanged();
}

bool MobileController::trustedUrl(const QUrl &url)
{
    return url.isValid() && url.scheme().toLower() == "https" &&
        (url.host().toLower() == "bb10-volte.octoooo.com" || url.host().toLower() == "bb10-downloads.octoooo.com") &&
        (url.port() == -1 || url.port() == 443) && url.userInfo().isEmpty() && !url.hasFragment() &&
        !url.path().contains("..") && !url.path().contains('\\');
}

void MobileController::checkUpdate()
{
    if (m_busy || jobRunning()) { fail("wait_job"); return; }
    m_update.clear(); m_metadata.clear(); m_error.clear();
    m_transfer = "metadata"; m_notice = "checking_update"; m_redirects = 0; m_busy = true;
    beginNetwork(QUrl(QLatin1String(LATEST_URL)));
}

void MobileController::beginNetwork(const QUrl &url)
{
    if (!trustedUrl(url)) { finishNetworkError("bad_update_metadata"); return; }
    QNetworkRequest request(url);
    request.setRawHeader("User-Agent", QByteArray("BB10VoLTE/") + BB10_MOBILE_VERSION);
    request.setRawHeader("Accept", m_transfer == "metadata" ? "application/json" : "application/zip");
    m_reply = m_network.get(request);
    m_reply->setReadBufferSize(64 * 1024);
    // QSslSocket's normal peer verification is retained. Never call ignoreSslErrors().
    connect(m_reply, SIGNAL(readyRead()), this, SLOT(networkReady()));
    connect(m_reply, SIGNAL(finished()), this, SLOT(networkFinished()));
    m_networkDeadline.start(m_transfer == "metadata" ? 30000 : 300000);
    emit modelChanged();
}

void MobileController::downloadUpdate()
{
    if (m_busy || jobRunning() || m_update.isEmpty()) return;
    if (!allowed("update")) { fail("action_unavailable"); return; }
    m_pendingAction = "download-update";
    m_pendingExtra.clear();
    m_pollTimer.stop();
    emit confirmationNeeded();
}

void MobileController::beginDownload()
{
    if (m_busy || jobRunning() || m_update.isEmpty() || !allowed("update")) { fail("action_unavailable"); return; }
    const QString filename = "/accounts/1000/shared/downloads/bb10-volte-update-" + newOperationId() + ".zip.part";
    if (QFileInfo(filename).exists() || QFileInfo(filename).isSymLink()) { fail("storage_denied"); return; }
    m_download.setFileName(filename);
    const int fd = ::open(filename.toLocal8Bit().constData(), O_WRONLY | O_CREAT | O_EXCL, 0600);
    if (fd < 0) { fail("storage_denied"); return; }
    if (!m_download.open(fd, QIODevice::WriteOnly, QFile::AutoCloseHandle)) { ::close(fd); fail("storage_denied"); return; }
    m_downloadBytes = 0; SHA256_Init(&m_downloadHash);
    m_transfer = "package"; m_error.clear(); m_notice = "downloading_update"; m_redirects = 0; m_busy = true;
    beginNetwork(QUrl(m_update.value("package_url").toString()));
}

void MobileController::networkReady()
{
    if (!m_reply || m_reply->attribute(QNetworkRequest::RedirectionTargetAttribute).isValid()) return;
    const QByteArray bytes = m_reply->readAll();
    if (m_transfer == "metadata") {
        m_metadata += bytes;
        if (m_metadata.size() > MAX_METADATA) finishNetworkError("bad_update_metadata");
    } else {
        m_downloadBytes += bytes.size();
        if (m_downloadBytes > MAX_PACKAGE || m_downloadBytes > m_update.value("size").toLongLong() ||
            m_download.write(bytes) != bytes.size()) { finishNetworkError("storage_denied"); return; }
        SHA256_Update(&m_downloadHash, bytes.constData(), bytes.size());
    }
}

void MobileController::networkFinished()
{
    if (!m_reply) return;
    const QVariant redirect = m_reply->attribute(QNetworkRequest::RedirectionTargetAttribute);
    if (redirect.isValid()) {
        const QUrl target = m_reply->url().resolved(redirect.toUrl());
        m_reply->deleteLater(); m_reply = 0;
        if (++m_redirects > 3 || !trustedUrl(target)) { finishNetworkError("bad_update_metadata"); return; }
        beginNetwork(target); return;
    }
    const int status = m_reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
    const QNetworkReply::NetworkError error = m_reply->error();
    if (error != QNetworkReply::NoError || status != 200) {
        const QString reason = error == QNetworkReply::SslHandshakeFailedError ? "tls_failed" :
            m_transfer == "metadata" && status == 404 ? "update_unpublished" : "download_failed";
        finishNetworkError(reason); return;
    }
    networkReady();
    if (!m_reply) return;
    m_reply->deleteLater(); m_reply = 0; m_networkDeadline.stop();
    if (m_transfer == "metadata") {
        QVariantMap metadata = parseObject(m_metadata);
        const qint64 size = metadata.value("size").toLongLong();
        const QString hash = bounded(metadata.value("sha256"), 64);
        const QUrl url(metadata.value("package_url").toString());
        m_busy = false;
        if (metadata.value("schema").toInt() != 2 || !trustedUrl(url) ||
            !QRegExp("^[a-f0-9]{64}$").exactMatch(hash) || size < 1 || size > MAX_PACKAGE ||
            !QRegExp("^[0-9]+(\\.[0-9]+){2,3}$").exactMatch(metadata.value("version").toString())) {
            finishNetworkError("bad_update_metadata"); return;
        }
        QString currentVersion = bounded(m_model.value("details").toMap().value("version"), 64);
        if (!QRegExp("^[0-9]+(\\.[0-9]+){2,3}$").exactMatch(currentVersion)) currentVersion = version();
        if (newerVersion(metadata.value("version").toString(), currentVersion)) { m_update = metadata; m_notice = "update_available"; }
        else m_notice = "up_to_date";
    } else {
        m_download.close();
        unsigned char digest[SHA256_DIGEST_LENGTH];
        SHA256_Final(digest, &m_downloadHash);
        const QString hash = QString::fromLatin1(QByteArray(reinterpret_cast<const char *>(digest), SHA256_DIGEST_LENGTH).toHex());
        if (m_downloadBytes != m_update.value("size").toLongLong() || hash != m_update.value("sha256").toString()) {
            finishNetworkError("package_changed"); return;
        }
        const QString final = m_download.fileName().left(m_download.fileName().size() - 5);
        if (!m_download.rename(final)) { finishNetworkError("storage_denied"); return; }
        m_packagePath = final; m_busy = false; m_transfer.clear();
        emit settingsChanged();
        // The preceding user confirmation covers download and installation; the runtime verifies the publisher signature.
        invoke("update"); return;
    }
    m_transfer.clear(); scheduleRefresh(); emit modelChanged();
}

void MobileController::finishNetworkError(const QString &code)
{
    m_networkDeadline.stop();
    if (m_reply) {
        QNetworkReply *reply = m_reply; m_reply = 0;
        reply->disconnect(this); reply->abort(); reply->deleteLater();
    }
    if (m_download.isOpen()) m_download.close();
    const QString partial = m_download.fileName();
    if (partial.startsWith("/accounts/1000/shared/downloads/bb10-volte-update-") &&
        partial.endsWith(".zip.part") && !QFileInfo(partial).isSymLink()) QFile::remove(partial);
    m_busy = false; m_transfer.clear(); m_notice.clear(); fail(code);
}

void MobileController::networkTimeout() { finishNetworkError("download_failed"); }
