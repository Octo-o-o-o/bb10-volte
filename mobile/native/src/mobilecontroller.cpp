#include "mobilecontroller.h"
#include "bundle_identity.h"
#include "ui_strings.h"
#include "state_strings.h"
#include <bb/cascades/Application>
#include <bb/cascades/ScreenIdleMode>
#include <bb/cascades/Window>
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
const qint64 MAX_PACKAGE = 32 * 1024 * 1024;
const int REQUEST_IDLE_TIMEOUT = 150000;
const int REQUEST_TOTAL_TIMEOUT = 900000;
const int NETWORK_IDLE_TIMEOUT = 150000;
const int METADATA_TOTAL_TIMEOUT = 300000;
const int PACKAGE_TOTAL_TIMEOUT = 1800000;
const char *LATEST_URL = "https://bb10-volte.octoooo.com/mobile/latest.json";

void setScreenAwake(bool awake)
{
    bb::cascades::Application::instance()->mainWindow()->setScreenIdleMode(
        awake ? bb::cascades::ScreenIdleMode::KeepAwake : bb::cascades::ScreenIdleMode::Normal);
}

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

QString jobActionForOperation(const QString &action)
{
    if (action == "backup-export" || action == "export") return "export";
    const QStringList jobs = QString("install,enable,disable,update,rollback,uninstall,legacy-install,legacy-start,legacy-stop,legacy-update,legacy-uninstall").split(',');
    return jobs.contains(action) ? action : QString();
}

QString bounded(const QVariant &value, int length = 4096)
{
    return value.type() == QVariant::String ? value.toString().left(length) : QString();
}

bool callPreSaveRejection(const QVariantMap &response)
{
    const QStringList codes = QString("call_context_changed,registration_no_longer_current,call_confirmation_incomplete,operation_in_progress,runtime_selection_changed").split(',');
    return response.value("schema").toInt() == 2 &&
           response.value("ok").type() == QVariant::Bool && !response.value("ok").toBool() &&
           !response.contains("job") && !response.contains("job_id") &&
           response.value("state").toString() == "error" &&
           codes.contains(bounded(response.value("error").toMap().value("code"), 80));
}

bool entryPreDispatchRejection(const QVariantMap &response)
{
    const QStringList codes = QString("bridge_bundle_changed,unsafe_bridge_entry").split(',');
    return response.value("schema").toInt() == 2 &&
           response.value("ok").type() == QVariant::Bool && !response.value("ok").toBool() &&
           !response.contains("job") && !response.contains("job_id") &&
           response.value("state").toString() == "error" &&
           codes.contains(bounded(response.value("error").toMap().value("code"), 80));
}

bool updatePreDispatchRejection(const QVariantMap &response)
{
    const QStringList codes = QString("invalid_update_expectation,update_runtime_upgrade_required").split(',');
    return response.value("schema").toInt() == 2 &&
           response.value("ok").type() == QVariant::Bool && !response.value("ok").toBool() &&
           !response.contains("job") && !response.contains("job_id") &&
           response.value("state").toString() == "error" &&
           codes.contains(bounded(response.value("error").toMap().value("code"), 80));
}

bool newerVersion(const QString &candidate, const QString &current)
{
    const QRegExp pattern("^[0-9]{1,5}(\\.[0-9]{1,5}){3}$");
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
    : QObject(parent), m_settings(), m_progressScanOffset(0), m_busy(false), m_timedOut(false), m_runtimeError(false),
      m_waitingForRoot(false), m_refreshLegacy(false),
      m_foreground(true), m_sleeping(false), m_experimentalVisible(false),
      m_pickerOpen(false), m_pickerClosed(false), m_pickerResultHandled(false), m_refreshPending(false), m_reconcilingCalls(false),
      m_cachedStatus(false), m_allowAutoPoll(false), m_invalidPendingIdentity(false), m_oneShotActive(false),
      m_preservePendingForRequest(false), m_newPendingForRequest(false),
      m_network(this), m_reply(0), m_downloadBytes(0), m_redirects(0)
{
    m_language = m_settings.value("language", QLocale::system().name().startsWith("zh") ? "zh" : "en").toString();
    if (m_language != "zh") m_language = "en";
    m_backupLocation = m_settings.value("backup_location", sdAvailable() ? "sdcard" : "internal").toString();
    if (m_backupLocation != "sdcard" || !sdAvailable()) m_backupLocation = "internal";
    m_legacyProfile = m_settings.value("legacy_profile", "china-mobile").toString();
    if (!knownProfile(m_legacyProfile)) m_legacyProfile = "china-mobile";
    const QVariant rawJob = m_settings.value("pending_job");
    const QVariant rawOperation = m_settings.value("pending_operation");
    m_jobId = rawJob.toString();
    m_operationId = rawOperation.toString();
    const QRegExp operationId("^[a-f0-9]{32}$");
    // Do not silently discard malformed or conflicting durable identities.
    // A later observation must never erase the original on-disk record.
    m_invalidPendingIdentity = m_settings.status() != QSettings::NoError ||
        (m_settings.contains("pending_job") && rawJob.type() != QVariant::String) ||
        (m_settings.contains("pending_operation") && rawOperation.type() != QVariant::String) ||
        (!m_jobId.isEmpty() && !operationId.exactMatch(m_jobId)) ||
        (!m_operationId.isEmpty() && !operationId.exactMatch(m_operationId)) ||
        (!m_jobId.isEmpty() && !m_operationId.isEmpty() && m_jobId != m_operationId);
    if (m_invalidPendingIdentity) { m_jobId.clear(); m_operationId.clear(); }
    m_operationAction = m_settings.value("pending_operation_action").toString();
    m_pendingCallContext = m_settings.value("pending_call_context").toString();
    if (m_operationId.isEmpty()) {
        m_operationAction.clear();
        m_pendingCallContext.clear();
    } else if (m_operationAction == "confirm-calls" &&
               QRegExp("^[a-f0-9]{32}$").exactMatch(m_pendingCallContext)) {
        m_reconcilingCalls = true;
    } else {
        m_pendingCallContext.clear();
        if (jobActionForOperation(m_operationAction).isEmpty()) m_operationAction.clear();
    }
    m_lastExportPath = m_settings.value("last_export_path").toString().left(2048);
    if (!m_lastExportPath.startsWith("/accounts/1000/shared/") &&
        !m_lastExportPath.startsWith("/accounts/1000/removable/sdcard/")) m_lastExportPath.clear();
    // Unknown work must be checked explicitly; never present an older success
    // or allow its call confirmation while a previous operation is unresolved.
    if (m_invalidPendingIdentity || !m_jobId.isEmpty() || !m_operationId.isEmpty()) {
        m_model.insert("state", "recovery_required");
        m_model.insert("primary_action", m_invalidPendingIdentity ? "compatibility" : m_jobId.isEmpty() ? "inspect" : "poll");
        m_cachedStatus = true;
    } else if (cachedModel(&m_model)) {
        m_cachedStatus = true;
    } else {
        // Older app versions did not record whether they had been opened.
        // Without a cache, ask for one explicit check instead of guessing that
        // an upgrade is a first install and starting an unsolicited check.
        m_model.insert("state", "not_checked");
        m_model.insert("primary_action", "inspect");
    }
    if (!m_invalidPendingIdentity && !m_jobId.isEmpty() &&
        (m_operationId.isEmpty() || m_operationId == m_jobId) && m_operationAction != "confirm-calls")
        m_coldPollJobId = m_jobId;
    connect(&m_process, SIGNAL(started()), this, SLOT(processStarted()));
    connect(&m_process, SIGNAL(readyReadStandardOutput()), this, SLOT(processOutput()));
    connect(&m_process, SIGNAL(readyReadStandardError()), this, SLOT(processErrorOutput()));
    connect(&m_process, SIGNAL(finished(int,QProcess::ExitStatus)), this, SLOT(processFinished(int,QProcess::ExitStatus)));
    connect(&m_process, SIGNAL(error(QProcess::ProcessError)), this, SLOT(processError(QProcess::ProcessError)));
    m_deadline.setSingleShot(true);
    connect(&m_deadline, SIGNAL(timeout()), this, SLOT(processTimeout()));
    m_pollTimer.setSingleShot(true);
    connect(&m_pollTimer, SIGNAL(timeout()), this, SLOT(poll()));
    m_screenIdleTimer.setSingleShot(true);
    connect(&m_screenIdleTimer, SIGNAL(timeout()), this, SLOT(releaseScreenAwake()));
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
    startScreenAwakeWindow();
    scheduleRefresh();
}

void MobileController::startScreenAwakeWindow()
{
    // A manual foreground/unlock gets ten minutes. Status polling, jobs and
    // network responses never renew this window or change the system timeout.
    if (!m_foreground || m_sleeping) return;
    setScreenAwake(true);
    m_screenIdleTimer.start(10 * 60 * 1000);
}

void MobileController::releaseScreenAwake()
{
    m_screenIdleTimer.stop();
    setScreenAwake(false);
}

bool MobileController::refreshBlocked() const
{
    return !m_foreground || m_sleeping || m_busy || m_pickerOpen || !m_pendingAction.isEmpty();
}

void MobileController::scheduleRefresh()
{
    m_pollTimer.stop();
    if (refreshBlocked()) return;
    if (!m_coldPollJobId.isEmpty()) { m_pollTimer.start(200); return; }
    if (!m_allowAutoPoll) return;
    if (m_experimentalVisible && m_jobId.isEmpty() && !m_refreshLegacy && !m_waitingForRoot) return;
    if (m_refreshPending || m_refreshLegacy) m_pollTimer.start(200);
    else if (!m_error.isEmpty()) return;
    else if (jobRunning()) m_pollTimer.start(1800);
}

void MobileController::enteredForeground()
{
    const bool wasForeground = m_foreground;
    m_foreground = true;
    if (!wasForeground) startScreenAwakeWindow();
    if (!wasForeground && !m_busy) {
        if (m_notice == "calls_saved_notice") m_notice.clear();
        if ((jobRunning() || m_reconcilingCalls) && m_allowAutoPoll) m_refreshPending = true;
        else { m_allowAutoPoll = false; m_cachedStatus = true; refreshUpdateAvailability(); emit modelChanged(); }
    }
    scheduleRefresh();
}

void MobileController::enteredBackground()
{
    m_foreground = false;
    releaseScreenAwake();
    m_pollTimer.stop();
}

void MobileController::screenAsleep()
{
    m_sleeping = true;
    releaseScreenAwake();
    m_pollTimer.stop();
}

void MobileController::screenAwake()
{
    const bool wasSleeping = m_sleeping;
    m_sleeping = false;
    if (wasSleeping) startScreenAwakeWindow();
    if (wasSleeping && m_foreground && !m_busy) {
        if (m_notice == "calls_saved_notice") m_notice.clear();
        if ((jobRunning() || m_reconcilingCalls) && m_allowAutoPoll) m_refreshPending = true;
        else { m_allowAutoPoll = false; m_cachedStatus = true; refreshUpdateAvailability(); emit modelChanged(); }
    }
    scheduleRefresh();
}

void MobileController::setExperimentalVisible(bool visible)
{
    if (m_experimentalVisible == visible) return;
    m_experimentalVisible = visible;
    if (!visible) {
        // Leaving a page is not an explicit request to check the phone.
        if (jobRunning() && m_allowAutoPoll) m_refreshPending = true;
        else { m_allowAutoPoll = false; m_cachedStatus = true; refreshUpdateAvailability(); emit modelChanged(); }
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
    const int field = key == "title" ? 0 : key == "message" ? 1 : key == "primary_label" ? 2 : -1;
    const QString state = bounded(m_model.value("state"), 80);
    // Older signed runtimes still return the previous mandatory-check and
    // restart wording. These known states have the same protocol meaning, so
    // the current client supplies its own presentation in either language.
    if (field >= 0 && (state == "registered" || state == "reboot_required" || state == "carrier_reboot_required")) {
        for (int i = 0; UI_STATE_STRINGS[i].state; ++i)
            if (state == QLatin1String(UI_STATE_STRINGS[i].state))
                return QString::fromUtf8(m_language == "zh" ? UI_STATE_STRINGS[i].zh[field] : UI_STATE_STRINGS[i].en[field]);
    }
    const QString localized = bounded(m_model.value("display_i18n").toMap().value(m_language).toMap().value(key));
    if (!localized.isEmpty()) return localized;
    // A response may arrive after the user changes language. Never label that
    // response using the language selected after its request was sent.
    const QString supplied = bounded(m_model.value("display").toMap().value(key));
    if (m_modelLanguage == m_language && !supplied.isEmpty()) return supplied;
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
    if (m_invalidPendingIdentity) return label(reportInProgress() ? "report_exporting" : "pending_identity_title");
    const QString completedJobState = m_model.value("job").toMap().value("state").toString();
    if (!m_busy && m_runtimeError && m_model.value("live_status").toBool() &&
        (completedJobState == "completed" || completedJobState == "complete" ||
         completedJobState == "succeeded" || completedJobState == "done"))
        return label("task_completed_status_unavailable");
    if (m_waitingForRoot && !m_busy) return label("state_waiting_root");
    if (callConfirmationInProgress()) return label(m_reconcilingCalls ? "calls_rechecking" : "calls_saving");
    if (m_busy && !m_timedOut && readAction(m_action)) return label(m_action == "poll" ? "checking_task" : "checking");
    if (reportInProgress()) return label("report_exporting");
    if (m_busy && m_transfer == "metadata") return label("checking_update");
    if (m_busy && m_transfer == "package") return label("downloading_update");
    if (m_error == "operation_unknown") return label("job_pending");
    if (!m_error.isEmpty()) {
        if (m_runtimeError && !display("title", "title_code").isEmpty()) return display("title", "title_code");
        const QString local = label(m_error);
        return local.isEmpty() ? label("operation_failed") : local;
    }
    if (m_cachedStatus && jobRunning() && !m_jobId.isEmpty()) return label("job_last_running");
    if (m_cachedStatus && (!m_operationId.isEmpty() || !m_jobId.isEmpty())) return label("job_pending");
    if (m_model.value("state").toString() == "not_checked") return label("state_not_checked");
    QString title = display("title", "title_code");
    if (title.isEmpty()) title = label("state_" + bounded(m_model.value("state"), 80));
    if (title.isEmpty()) title = label("checking");
    if (m_model.value("state").toString() == "task_complete_status_unchecked") return title;
    return m_cachedStatus && m_operationId.isEmpty() && m_jobId.isEmpty()
        ? label("cached_title_prefix") + title : title;
}

QString MobileController::statusMessage() const
{
    if (m_invalidPendingIdentity) {
        if (reportInProgress()) return label("report_exporting_help");
        QString reason = label(m_error);
        if (!m_error.isEmpty() && reason.isEmpty()) reason = label("operation_failed");
        return label("pending_identity_unreadable") + (reason.isEmpty() ? QString() : "\n\n" + reason);
    }
    if (m_waitingForRoot && !m_busy) return label("root_waiting_help");
    if (callConfirmationInProgress()) return label(m_reconcilingCalls ? "calls_rechecking_help" : "calls_saving_help");
    if (m_busy && !m_timedOut && readAction(m_action)) return label(m_action == "poll" ? "checking_task_help" : "checking_help");
    if (reportInProgress()) return label("report_exporting_help");
    if (m_busy && !m_transfer.isEmpty()) return label("network_wait_help");
    if (m_runtimeError) {
        if (m_error == "management_busy" && !display("message", "message_code").isEmpty()) return display("message", "message_code");
        const QString reason = label(m_error);
        if (!reason.isEmpty()) return reason;
        if (!display("message", "message_code").isEmpty()) return display("message", "message_code");
    }
    if (m_error == "root_not_ready") return label("root_help");
    if (m_error == "operation_unknown") return label("operation_unknown");
    if (!m_error.isEmpty()) return label("inspect");
    if (m_cachedStatus && jobRunning() && !m_jobId.isEmpty()) return label("job_last_running_help");
    if (!m_busy && ((!m_operationId.isEmpty() && m_jobId.isEmpty()) ||
                    (m_cachedStatus && !m_jobId.isEmpty()))) return label("operation_unknown");
    if (m_model.value("state").toString() == "not_checked") return label("state_not_checked_help");
    const QString state = m_model.value("state").toString();
    if (state == "task_complete_status_unchecked") return display("message", "message_code");
    if (m_cachedStatus && state == "registered") return label("cached_registered_help");
    if (m_cachedStatus && state == "verified") return label("cached_verified_help");
    if (m_cachedStatus && (state == "waiting" || state == "waiting_sim" ||
                           state == "waiting_ims" || state == "waiting_ims_apn"))
        return label("cached_wait_help");
    if (m_cachedStatus && m_operationId.isEmpty() && m_jobId.isEmpty()) return label("cached_general_help");
    return display("message", "message_code");
}

bool MobileController::reportInProgress() const
{
    return m_busy && !m_timedOut && (m_action == "compatibility" ||
        (m_action == "export" && (m_preservePendingForRequest || m_operationAction != "backup-export")));
}

QString MobileController::primaryAction() const
{
    if (m_invalidPendingIdentity) return "compatibility";
    const QString action = bounded(m_model.value("primary_action"), 64);
    if (!m_error.isEmpty() && !(m_runtimeError && action == "resume" && !m_jobId.isEmpty() && allowed(action))) return "inspect";
    if (m_model.value("state").toString() == "job_outcome_unknown" && action == "export" && allowed(action)) return action;
    if (!m_operationId.isEmpty() && action != "resume" && action != "poll") return m_jobId.isEmpty() ? "inspect" : "poll";
    // Older runtimes made call confirmation the primary action; keep it as an
    // optional secondary action even when the installed runtime predates this UI.
    if (m_model.value("state").toString() == "registered" && action == "confirm-calls")
        return !m_jobId.isEmpty() ? "poll" : m_cachedStatus ? "inspect" : "status";
    if (m_cachedStatus && action != "confirm-calls") return !m_jobId.isEmpty() ? "poll" : "inspect";
    // Experimental actions are intentionally never promoted to the home button.
    if (!knownAction(action) || action.startsWith("legacy-") || (action == "poll" && m_jobId.isEmpty())) return "inspect";
    return action;
}

QString MobileController::primaryText() const
{
    if (m_invalidPendingIdentity) return label("compatibility");
    if (primaryAction() == "resume" || primaryAction() == "poll") return label(primaryAction());
    if (m_cachedStatus && primaryAction() != "confirm-calls") return label("status");
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

QString MobileController::compatibilityText() const
{
    QFile file(QDir::current().absoluteFilePath("app/native/assets/materials/compatibility-matrix.json"));
    if (!file.open(QIODevice::ReadOnly) || file.size() > 131072) return QString();
    const QVariantMap data = parseObject(file.readAll());
    const QVariantMap row = data.value("models").toMap().value(deviceText()).toMap();
    return row.value("summary").toMap().value(m_language == "en" ? "en" : "zh").toString().left(2048);
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
    if (m_cachedStatus && jobRunning()) return QString();
    const QString view = m_model.value("state").toString();
    if (!m_error.isEmpty() || view == "export_interrupted" || view == "job_outcome_unknown") return QString();
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
QString MobileController::updateFeedback() const
{
    QString message = label(m_updateFeedback);
    if (message.isEmpty() && !m_updateFeedback.isEmpty()) message = label("operation_failed");
    const QVariantMap job = m_model.value("job").toMap();
    const QString state = job.value("state").toString();
    if (!message.isEmpty() && m_runtimeError && m_updateFeedback == m_error &&
        m_model.value("live_status").toBool() && job.value("action").toString() == "update" &&
        (state == "completed" || state == "complete" || state == "succeeded" || state == "done"))
        return label("task_completed_status_unavailable") + "\n" + message;
    return message;
}
QString MobileController::cachedStatusText() const
{
    if (m_invalidPendingIdentity) return QString();
    if (m_model.value("state").toString() == "task_complete_status_unchecked") return QString();
    if (m_busy && readAction(m_action) && m_operationId.isEmpty() && m_jobId.isEmpty() &&
        m_model.value("state").toString() != "not_checked") return label("previous_status_refreshing");
    return m_cachedStatus && m_operationId.isEmpty() && m_jobId.isEmpty() &&
           m_model.value("state").toString() != "not_checked" ? label("cached_status_note") : QString();
}
QString MobileController::updateBlockMessage() const
{
    if (m_busy || (!hasUpdate() && !hasPackage()) || allowed("update")) return QString();
    if (m_invalidPendingIdentity) return label("pending_identity_unreadable");
    if (!m_operationId.isEmpty() || !m_jobId.isEmpty()) return label("update_blocked_pending");
    if (m_cachedStatus) return label("update_blocked_cached");
    return label("update_blocked_state");
}
QString MobileController::runtimeVersionText() const
{
    const QString value = bounded(m_model.value("details").toMap().value("version"), 40);
    if (!QRegExp("^[0-9]{1,5}(\\.[0-9]{1,5}){3}$").exactMatch(value)) return label("unknown");
    return value + (m_cachedStatus ? label("cached_version_suffix") : QString());
}
QString MobileController::phoneServiceText() const
{
    const QString value = bounded(m_model.value("details").toMap().value("service_state"), 20);
    const QStringList states = QString("installed,absent,legacy,pending").split(',');
    const QString text = states.contains(value) ? label("service_" + value) : label("unknown");
    return text + (m_cachedStatus && states.contains(value) ? label("cached_version_suffix") : QString());
}
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

bool MobileController::activityVisible() const
{
    return m_busy || (jobRunning() && m_error.isEmpty() && m_allowAutoPoll);
}

bool MobileController::operationInProgress() const
{
    // A failed observation must reveal its recovery UI rather than leave a
    // modal spinner over stale job data. Reboot/network waits are not jobs.
    if (!m_error.isEmpty()) return false;
    const QStringList changes = QString("install,enable,disable,update,rollback,uninstall,legacy-install,legacy-start,legacy-stop,legacy-update,legacy-uninstall").split(',');
    const QString jobAction = m_model.value("job").toMap().value("action").toString();
    return callConfirmationInProgress() ||
           (m_busy && m_action == "export" && m_operationAction == "backup-export" && !m_preservePendingForRequest) ||
           (jobRunning() && m_allowAutoPoll && jobAction == "export") ||
           (m_busy && (changes.contains(m_action) || (m_action == "resume" && changes.contains(jobAction)))) ||
           (jobRunning() && m_allowAutoPoll && changes.contains(jobAction));
}

bool MobileController::callConfirmationInProgress() const
{
    return (m_busy && m_action == "confirm-calls") ||
           (m_reconcilingCalls && ((!m_busy && m_refreshPending) ||
             (m_busy && (m_action == "inspect" || m_action == "status" || m_action == "poll"))));
}

bool MobileController::updateTaskRequest() const
{
    const bool checkingTask = m_action == "inspect" || m_action == "status" || m_action == "poll" || m_action == "resume";
    return m_action == "update" || (checkingTask && (m_operationAction == "update" ||
           (!m_jobId.isEmpty() && m_model.value("job").toMap().value("action").toString() == "update")));
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
    if (m_invalidPendingIdentity) return action == "compatibility" || action == "export";
    if (readAction(action)) return true;
    // An accepted observation already covers this context. A manual check
    // can discover a changed SIM or boot before another confirmation.
    if (action == "confirm-calls" && m_model.value("state").toString() == "verified") return false;
    // Never start a second write while an earlier operation's result is
    // unknown. A report uses a separate ID; resume addresses the same job.
    if ((!m_operationId.isEmpty() || !m_jobId.isEmpty()) && action != "compatibility" && action != "export" &&
        !(action == "resume" && !m_jobId.isEmpty())) return false;
    // A cached call screen is only a convenience. The Root worker probes the
    // current boot, SIM and IMS again before it saves any confirmation.
    if (m_cachedStatus && action != "confirm-calls" && action != "compatibility" && action != "export") return false;
    if (jobRunning()) return false;
    if (action.startsWith("legacy-") && m_checkedLegacyProfile != m_legacyProfile) return false;
    if (action == "compatibility") return true;
    if (action == "export" && (m_cachedStatus || !m_operationId.isEmpty() || !m_jobId.isEmpty())) return true;
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

bool MobileController::cachedModel(QVariantMap *model) const
{
    const QVariantMap cache = m_settings.value("last_observation_v1").toMap();
    const QString state = bounded(cache.value("state"), 80);
    // Only informational states can be cached. In particular, never replay a
    // stale restart instruction, recovery decision, job or write authorization.
    const QStringList states = QString("ready_to_install,mobile_network_off,mobile_network_auto_enable,registered,verified,disabled,update_ready,waiting,waiting_sim,waiting_ims,waiting_ims_apn,unsupported,sim_unsupported,uninstalled,ready_after_uninstall").split(',');
    if (cache.value("schema").toInt() != 1 || !states.contains(state)) return false;
    QVariantMap details;
    QVariantMap device;
    const QVariantMap savedDetails = cache.value("details").toMap();
    const QVariantMap savedDevice = savedDetails.value("device").toMap();
    const QStringList deviceFields = QString("variant,os_version,board_type").split(',');
    for (int i = 0; i < deviceFields.size(); ++i) {
        const QString value = bounded(savedDevice.value(deviceFields.at(i)), 120);
        if (QRegExp("^[A-Za-z0-9_.-]{1,120}$").exactMatch(value)) device.insert(deviceFields.at(i), value);
    }
    const QString carrier = bounded(savedDetails.value("carrier"), 16);
    details.insert("device", device);
    details.insert("carrier", QString("mobile,unicom,telecom").split(',').contains(carrier) ? carrier : "unknown");
    const QString phase = bounded(savedDetails.value("phase"), 80);
    if (QRegExp("^[a-z0-9_]{1,80}$").exactMatch(phase)) details.insert("phase", phase);
    const QString oldVersion = bounded(savedDetails.value("version"), 40);
    if (QRegExp("^[0-9.]{1,40}$").exactMatch(oldVersion)) details.insert("version", oldVersion);
    const QString serviceState = bounded(savedDetails.value("service_state"), 20);
    if (QString("installed,absent,legacy,pending").split(',').contains(serviceState)) details.insert("service_state", serviceState);
    QVariantList actions;
    actions << QVariant("status") << QVariant("compatibility");
    QString action = "inspect";
    const QString context = bounded(cache.value("call_context"), 32);
    const bool hasCallContext = state == "registered" && QRegExp("^[a-f0-9]{32}$").exactMatch(context);
    if (hasCallContext) {
        // This token can only prefill the user's screen; the worker's fresh
        // probe and boot/SIM/payload binding are mandatory before saving.
        actions << QVariant("confirm-calls");
    }
    model->clear();
    model->insert("schema", 2);
    model->insert("state", state);
    model->insert("primary_action", action);
    model->insert("actions", actions);
    model->insert("details", details);
    if (hasCallContext) model->insert("call_context", context);
    return true;
}

void MobileController::saveCachedModel(const QVariantMap &response)
{
    const QString state = bounded(response.value("state"), 80);
    const QStringList states = QString("ready_to_install,mobile_network_off,mobile_network_auto_enable,registered,verified,disabled,update_ready,waiting,waiting_sim,waiting_ims,waiting_ims_apn,unsupported,sim_unsupported,uninstalled,ready_after_uninstall").split(',');
    if (!states.contains(state)) {
        m_settings.remove("last_observation_v1");
        return;
    }
    const QVariantMap details = response.value("details").toMap();
    const QVariantMap sourceDevice = details.value("device").toMap();
    QVariantMap device;
    device.insert("variant", bounded(sourceDevice.value("variant"), 120));
    device.insert("os_version", bounded(sourceDevice.value("os_version"), 120));
    device.insert("board_type", bounded(sourceDevice.value("board_type"), 120));
    QVariantMap safeDetails;
    safeDetails.insert("device", device);
    safeDetails.insert("carrier", bounded(details.value("carrier"), 16));
    safeDetails.insert("phase", bounded(details.value("phase"), 80));
    safeDetails.insert("version", bounded(details.value("version"), 40));
    safeDetails.insert("service_state", bounded(details.value("service_state"), 20));
    QVariantMap cache;
    cache.insert("schema", 1);
    cache.insert("state", state);
    cache.insert("details", safeDetails);
    const QString context = bounded(response.value("call_context"), 32);
    if (state == "registered" && QRegExp("^[a-f0-9]{32}$").exactMatch(context))
        cache.insert("call_context", context);
    m_settings.setValue("last_observation_v1", cache);
}

bool MobileController::restoreCachedAfterReadFailure(const QString &notice)
{
    if (m_invalidPendingIdentity || !m_jobId.isEmpty() || !m_operationId.isEmpty()) return false;
    QVariantMap cached;
    if (!cachedModel(&cached)) return false;
    m_model = cached;
    m_modelLanguage.clear();
    m_cachedStatus = true;
    m_allowAutoPoll = false;
    m_refreshPending = false;
    m_error.clear();
    m_runtimeError = false;
    m_waitingForRoot = false;
    m_notice = notice;
    emit modelChanged();
    return true;
}

void MobileController::fail(const QString &code)
{
    const QString safe = QRegExp("^[a-z0-9_-]{1,80}$").exactMatch(code) ? code : "operation_failed";
    m_runtimeError = false;
    if (m_model.value("state").toString() == "job_outcome_unknown" &&
        (!m_jobId.isEmpty() || !m_operationId.isEmpty())) {
        // A failed report or observation is secondary to the unresolved
        // device transaction. Keep its instructions and show this as a notice.
        m_waitingForRoot = false;
        m_error.clear();
        m_notice = label(safe).isEmpty() ? "operation_failed" : safe;
        emit modelChanged();
        return;
    }
    m_waitingForRoot = code == "root_not_ready" || code == "root_required";
    m_error = safe;
    emit modelChanged();
}

void MobileController::invoke(const QString &action, const QVariantMap &extra)
{
    // A manual read addresses the saved job. A separate diagnostic report
    // does not, and must leave the one-shot intent queued until it finishes.
    if (!m_oneShotActive && (action == "inspect" || action == "status" || action == "poll")) m_coldPollJobId.clear();
    if (!allowed(action) || m_process.state() != QProcess::NotRunning) { fail("action_unavailable"); return; }
    m_preservePendingForRequest = false;
    m_newPendingForRequest = false;
    m_reportOperationId.clear();
    m_pollTimer.stop();
    m_allowAutoPoll = !m_oneShotActive; // A cold-start check addresses the saved task exactly once.
    QByteArray entryBytes;
    QString bundlePath;
    if (!verifyEntry(&entryBytes, &bundlePath)) return;
    if (!QFileInfo("/bin/__root").isExecutable()) {
        if (readAction(action) && restoreCachedAfterReadFailure("root_not_ready")) return;
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
    if (action == "update" && !m_packagePath.isEmpty() && !m_expectedUpdateVersion.isEmpty()) {
        request.insert("expected_version", m_expectedUpdateVersion);
        request.insert("expected_sha256", m_expectedUpdateSha256);
    }
    if (!m_jobId.isEmpty() && (action == "poll" || action == "resume" || action == "inspect" || action == "status")) request.insert("job_id", m_jobId);
    else if ((action == "inspect" || action == "status") && !m_operationId.isEmpty() &&
             m_operationAction != "confirm-calls") request.insert("job_id", m_operationId);
    const bool report = action == "compatibility" ||
                        (action == "export" && extra.value("export_kind", "diagnostics").toString() == "diagnostics");
    if (action == "export" && !report && !m_operationId.isEmpty()) { fail("operation_unknown"); return; }
    if (!readAction(action) && report) {
        // Reports are synchronous, independently named exports. A lost report
        // reply must not create or overwrite a durable management transaction.
        m_preservePendingForRequest = m_invalidPendingIdentity || !m_operationId.isEmpty() || !m_jobId.isEmpty();
        m_reportOperationId = newOperationId();
        request.insert("operation_id", m_reportOperationId);
        if (!m_jobId.isEmpty() || !m_operationId.isEmpty()) {
            // Conflicting durable identities cannot identify one task; a
            // diagnostic must not accidentally describe a different client.
            if (m_jobId.isEmpty() || m_operationId.isEmpty() || m_jobId == m_operationId)
                request.insert("job_id", m_jobId.isEmpty() ? m_operationId : m_jobId);
        } else {
            const QVariantMap lastJob = m_model.value("job").toMap();
            const QString lastState = bounded(lastJob.value("state"), 32);
            const QString lastId = bounded(lastJob.value("id"), 96);
            if ((lastState == "failed" || lastState == "interrupted") && safeId(lastId))
                request.insert("job_id", lastId);
        }
    } else if (!readAction(action) && action == "resume") {
        if (!QRegExp("^[a-f0-9]{32}$").exactMatch(m_jobId) ||
            (!m_operationId.isEmpty() && m_operationId != m_jobId)) { fail("operation_unknown"); return; }
        if (m_operationId.isEmpty()) {
            // This job may have been created by another client or survived an
            // app reinstall. Resuming addresses that identity, never a new one.
            m_operationId = m_jobId;
            m_operationAction = m_model.value("job").toMap().value("action").toString();
            if (jobActionForOperation(m_operationAction).isEmpty()) m_operationAction.clear();
            m_settings.setValue("pending_operation", m_operationId);
            m_settings.setValue("pending_operation_action", m_operationAction);
            m_settings.sync();
            if (m_settings.status() != QSettings::NoError) { clearPendingOperation(); fail("state_storage_failed"); return; }
        }
        request.insert("operation_id", m_operationId);
    } else if (!readAction(action)) {
        m_operationId = newOperationId();
        m_newPendingForRequest = true;
        m_operationAction = action == "export" ? "backup-export" : action;
        m_pendingCallContext = action == "confirm-calls" ? extra.value("call_context").toString() : QString();
        m_reconcilingCalls = false;
        m_settings.setValue("pending_operation", m_operationId);
        m_settings.setValue("pending_operation_action", m_operationAction);
        m_settings.setValue("pending_call_context", m_pendingCallContext);
        m_settings.sync();
        if (m_settings.status() != QSettings::NoError) {
            // Nothing has been sent to Root. Do not start an operation whose
            // identity might be lost if the application closes or times out.
            clearPendingOperation();
            m_newPendingForRequest = false;
            m_allowAutoPoll = false;
            fail("state_storage_failed");
            return;
        }
    }
    if (!m_operationId.isEmpty() && !request.contains("operation_id")) request.insert("operation_id", m_operationId);
    bb::data::JsonDataAccess json;
    QByteArray payload;
    json.saveToBuffer(request, &payload);
    if (json.hasError() || payload.size() > 16384) {
        if (m_newPendingForRequest) { clearPendingOperation(); m_settings.sync(); m_newPendingForRequest = false; }
        fail("invalid_response"); return;
    }
    m_action = action;
    m_requestedLegacyProfile = action == "legacy-inspect" ? extra.value("profile_id").toString() : QString();
    m_output.clear();
    m_progressScanOffset = 0;
    m_requestElapsed.start();
    m_timedOut = false;
    m_runtimeError = false;
    m_waitingForRoot = false;
    m_error.clear();
    if (!m_oneShotActive) m_notice.clear();
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
    resetRequestDeadline();
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
    int end = m_output.indexOf('\n', m_progressScanOffset);
    while (end >= 0) {
        if (m_output.mid(m_progressScanOffset, end - m_progressScanOffset).trimmed() == "BB10_PROGRESS:1" &&
            !m_timedOut && m_deadline.isActive()) resetRequestDeadline();
        m_progressScanOffset = end + 1;
        end = m_output.indexOf('\n', m_progressScanOffset);
    }
    if (m_output.size() > MAX_RESPONSE) { m_timedOut = true; m_process.kill(); fail("invalid_response"); }
}

int MobileController::requestTimeoutForElapsed(qint64 elapsed)
{
    const qint64 remaining = REQUEST_TOTAL_TIMEOUT - elapsed;
    return int(qMax(qint64(1), qMin(qint64(REQUEST_IDLE_TIMEOUT), remaining)));
}

void MobileController::resetRequestDeadline()
{
    m_deadline.start(requestTimeoutForElapsed(m_requestElapsed.elapsed()));
}

void MobileController::processErrorOutput()
{
    // Root diagnostics can contain device identifiers. Never display or persist raw stderr.
    m_process.readAllStandardError();
}

void MobileController::processError(QProcess::ProcessError error)
{
    if (error != QProcess::FailedToStart) return;
    const bool updateRequest = updateTaskRequest();
    m_deadline.stop();
    m_busy = false;
    m_reconcilingCalls = false;
    if (m_newPendingForRequest) { clearPendingOperation(); m_settings.sync(); m_newPendingForRequest = false; }
    if (updateRequest) m_updateFeedback = "root_not_ready";
    const bool restored = readAction(m_action) && restoreCachedAfterReadFailure("root_not_ready");
    m_action.clear();
    m_preservePendingForRequest = false;
    if (m_oneShotActive) { m_oneShotActive = false; m_allowAutoPoll = false; m_refreshPending = false; }
    if (restored) { emit modelChanged(); return; }
    fail("root_not_ready");
    scheduleRefresh();
}

void MobileController::processTimeout()
{
    m_timedOut = true;
    if (m_action == "confirm-calls") reconcileCallConfirmation();
    else {
        m_reconcilingCalls = false;
        const bool report = m_action == "compatibility" ||
            (m_action == "export" && (m_preservePendingForRequest || m_operationAction != "backup-export"));
        if (!(readAction(m_action) && restoreCachedAfterReadFailure("request_timeout")))
            fail(readAction(m_action) ? "request_timeout" : report ? "report_unknown" : "operation_unknown");
    }
    if (updateTaskRequest() && !m_error.isEmpty()) { m_updateFeedback = m_error; emit modelChanged(); }
    m_process.kill();
}

void MobileController::clearPendingOperation()
{
    if (m_invalidPendingIdentity) return;
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
           !response.contains("job") && !response.contains("job_id") &&
           response.value("state").toString() == "verified" &&
           response.value("call_context").toString() == m_pendingCallContext;
}

bool MobileController::currentCallObservation(const QVariantMap &response) const
{
    if (m_operationAction != "confirm-calls" || m_operationId.isEmpty() || !readAction(m_action) ||
        response.value("schema").toInt() != 2 || response.value("ok").type() != QVariant::Bool ||
        !response.value("ok").toBool()) return false;
    const QString state = response.value("state").toString();
    const QString context = response.value("call_context").toString();
    const QVariantMap job = response.value("job").toMap();
    return (state == "registered" || state == "verified") &&
           QRegExp("^[a-f0-9]{32}$").exactMatch(context) &&
           (job.isEmpty() || job.value("state").toString() == "completed");
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
    bool updateRequest = updateTaskRequest();
    bool acceptedResponse = false;
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
        if (updateRequest && !m_error.isEmpty()) m_updateFeedback = m_error;
        m_action.clear();
        m_preservePendingForRequest = false;
        m_newPendingForRequest = false;
        if (m_oneShotActive) { m_oneShotActive = false; m_allowAutoPoll = false; m_refreshPending = false; m_refreshLegacy = false; }
        scheduleRefresh();
        emit modelChanged();
        return;
    }
    if (response.isEmpty()) {
        if (m_action == "confirm-calls") reconcileCallConfirmation();
        else {
            m_reconcilingCalls = false;
            const bool report = m_action == "compatibility" ||
                (m_action == "export" && (m_preservePendingForRequest || m_operationAction != "backup-export"));
            const QString reason = !readAction(m_action) ? (report ? "report_unknown" : "operation_unknown") :
                (code != 0 || status != QProcess::NormalExit ? "root_not_ready" : "invalid_response");
            if (!(readAction(m_action) && restoreCachedAfterReadFailure(reason))) fail(reason);
        }
    } else if (m_action == "confirm-calls" && !confirmedCallResponse(response) &&
               !callPreSaveRejection(response) && !entryPreDispatchRejection(response)) {
        // Only a matching acknowledgement or a proven pre-save rejection can
        // settle this request. Other outcomes get one check, never a new save.
        reconcileCallConfirmation();
    } else if (response.value("schema").toInt() != 2) {
        m_reconcilingCalls = false;
        fail("protocol_mismatch");
    } else {
        acceptedResponse = acceptResponse(response);
        if (acceptedResponse && response.value("job").toMap().value("action").toString() == "update") updateRequest = true;
        m_reconcilingCalls = false;
    }
    if (updateRequest) {
        if (!m_error.isEmpty()) m_updateFeedback = m_error;
        else if (acceptedResponse && response.value("ok").type() == QVariant::Bool && response.value("ok").toBool())
            m_updateFeedback = response.value("state").toString() == "job_outcome_unknown" ? "operation_unknown" : QString();
    }
    m_action.clear();
    m_preservePendingForRequest = false;
    m_newPendingForRequest = false;
    if (m_oneShotActive) { m_oneShotActive = false; m_allowAutoPoll = false; m_refreshPending = false; m_refreshLegacy = false; }
    scheduleRefresh();
    emit modelChanged();
}

bool MobileController::acceptResponse(const QVariantMap &response)
{
    if (m_preservePendingForRequest) {
        // A separate diagnostic report cannot replace the original task's
        // state, identity, or recovery instructions.
        const QVariantMap details = response.value("details").toMap();
        const QString path = bounded(details.value("export_path", details.value("path")), 2048);
        const bool validPath = QRegExp("^[a-f0-9]{32}$").exactMatch(m_reportOperationId) &&
            (path == "/accounts/1000/shared/documents/BB10-VoLTE/" + m_reportOperationId ||
             path == "/accounts/1000/removable/sdcard/BB10-VoLTE/" + m_reportOperationId);
        if (response.value("ok").type() == QVariant::Bool && response.value("ok").toBool() &&
            response.value("state").toString() == "exported" && validPath) {
            m_lastExportPath = path;
            m_settings.setValue("last_export_path", path);
            m_settings.sync();
            m_notice = "report_exported";
            emit settingsChanged();
        } else {
            const QString code = bounded(response.value("error").toMap().value("code"), 80);
            fail(code.isEmpty() ? "report_unknown" : code);
        }
        emit modelChanged();
        return false;
    }
    const QVariantMap responseJob = response.value("job").toMap();
    const QString nestedId = bounded(responseJob.value("id"), 96);
    const QString topId = bounded(response.value("job_id"), 96);
    const QString responseId = response.contains("job_id") ? topId : nestedId;
    const bool pending = !m_jobId.isEmpty() || !m_operationId.isEmpty();
    const QString observationError = bounded(response.value("error").toMap().value("code"), 80);
    if (pending && readAction(m_action) && response.value("schema").toInt() == 2 &&
        response.value("ok").type() == QVariant::Bool && !response.value("ok").toBool() &&
        response.value("state").toString() == "error" && !response.contains("job") && !response.contains("job_id") &&
        (observationError == "root_required" || observationError == "root_not_ready")) {
        // Root readiness is an observation failure, never a transaction result.
        fail(observationError);
        return false;
    }
    if (pending && m_model.value("state").toString() == "job_outcome_unknown" &&
        (response.value("state").toString() != "job_outcome_unknown" || responseJob.isEmpty() || responseId.isEmpty() ||
         (response.value("ok").type() == QVariant::Bool && !response.value("ok").toBool()))) {
        // A failed or identity-free observation cannot settle an already
        // established unknown outcome, even if the Root entry responded.
        const QString code = bounded(response.value("error").toMap().value("code"), 80);
        fail(code.isEmpty() ? "operation_unknown" : code);
        return false;
    }
    const bool hasJobMetadata = response.contains("job") || response.contains("job_id");
    const bool invalidIdentity = hasJobMetadata &&
        (responseJob.isEmpty() || !safeId(nestedId) || (response.contains("job_id") && topId != nestedId));
    const QString expectedAction = jobActionForOperation(m_operationAction);
    const bool wrongJob = !m_jobId.isEmpty() && responseId != m_jobId;
    const bool wrongOperation = !m_operationId.isEmpty() && (responseId != m_operationId ||
        (!expectedAction.isEmpty() && responseJob.value("action").toString() != expectedAction));
    const bool taskIdentityRequired = !m_jobId.isEmpty() ||
        (!m_operationId.isEmpty() && m_operationAction != "confirm-calls");
    const bool preDispatch = m_newPendingForRequest && m_jobId.isEmpty() &&
        (entryPreDispatchRejection(response) ||
         (m_action == "update" && updatePreDispatchRejection(response)) ||
         (callPreSaveRejection(response) && response.value("error").toMap().value("code").toString() == "runtime_selection_changed"));
    if (taskIdentityRequired && (responseJob.isEmpty() || !safeId(responseId)) && !preDispatch) {
        // A management write is asynchronous. An identity-free response can
        // neither prove it was rejected nor settle its durable operation ID.
        fail("operation_unknown");
        return false;
    }
    if (!preDispatch && !responseJob.isEmpty()) {
        const QVariant ok = response.value("ok");
        const QString jobState = responseJob.value("state").toString();
        const QStringList runningStates = QString("queued,running,pending,starting,waiting_reboot,interrupted").split(',');
        const bool success = jobState == "complete" || jobState == "completed" || jobState == "succeeded" || jobState == "done";
        const bool failed = jobState == "failed" || jobState == "cancelled";
        const bool unknownOutcome = response.value("state").toString() == "job_outcome_unknown" &&
            (jobState == "failed" || jobState == "interrupted") && ok.type() == QVariant::Bool && ok.toBool();
        const QString probeError = bounded(response.value("error").toMap().value("code"), 80);
        const bool completedProbeFailure = success && ok.type() == QVariant::Bool && !ok.toBool() &&
            response.value("live_status").type() == QVariant::Bool && response.value("live_status").toBool() &&
            response.value("state").toString() == "error" &&
            QRegExp("^[a-z0-9_-]{1,80}$").exactMatch(probeError);
        if (ok.type() != QVariant::Bool || (!success && !failed && !runningStates.contains(jobState)) ||
            (success && !ok.toBool() && !completedProbeFailure) || (failed && ok.toBool() && !unknownOutcome) ||
            (runningStates.contains(jobState) && !ok.toBool())) {
            fail("operation_unknown");
            return false;
        }
    }
    if (!m_preservePendingForRequest &&
        (invalidIdentity || (safeId(responseId) && (wrongJob || wrongOperation)))) {
        // A different client's task cannot establish the result of ours.
        fail("operation_unknown");
        return false;
    }
    if (readAction(m_action) && !hasJobMetadata && response.value("ok").type() == QVariant::Bool &&
        !response.value("ok").toBool() && !response.value("details").toMap().value("mobile_network_off").toBool() &&
        restoreCachedAfterReadFailure("inspection_unavailable")) return false;
    if (m_action == "confirm-calls" && confirmedCallResponse(response)) m_notice = "calls_saved_notice";
    m_model = response;
    m_cachedStatus = m_oneShotActive && jobRunning();
    m_modelLanguage = m_requestLanguage;
    const QVariantMap error = response.value("error").toMap();
    QVariantMap job = response.value("job").toMap();
    m_runtimeError = response.value("ok").type() == QVariant::Bool && !response.value("ok").toBool();
    if (m_runtimeError) {
        m_error = bounded(error.value("code", job.value("error_code")), 80);
        if (m_error.isEmpty()) m_error = "operation_failed";
    }
    if (m_action == "update" && m_newPendingForRequest && m_jobId.isEmpty() &&
        responseId.isEmpty() && responseJob.isEmpty() && m_runtimeError &&
        updatePreDispatchRejection(response)) {
        // These entry-point rejections precede dispatch and cannot have
        // created a background job or changed the device.
        clearPendingOperation();
    }
    if (m_newPendingForRequest && m_jobId.isEmpty() && responseId.isEmpty() && responseJob.isEmpty() &&
        m_runtimeError && ((m_error == "runtime_selection_changed" && callPreSaveRejection(response)) ||
                           entryPreDispatchRejection(response)) &&
        response.value("state").toString() == "error") {
        // The worker rejects this under the transaction lock before creating
        // or changing a task. Existing resume identities remain untouched.
        clearPendingOperation();
    }
    if (m_action == "confirm-calls" && m_operationAction == "confirm-calls" &&
        m_runtimeError && (callPreSaveRejection(response) || entryPreDispatchRejection(response))) {
        // These explicit worker rejections occur before the call record write.
        // Unknown failures and timeouts retain the original pending identity.
        if (m_error == "call_context_changed" || m_error == "registration_no_longer_current")
            m_settings.remove("last_observation_v1");
        clearPendingOperation();
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
    if (safeId(id) && !m_preservePendingForRequest) {
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
    const bool unknownOutcome = response.value("state").toString() == "job_outcome_unknown";
    const bool interruptedExport = response.value("state").toString() == "export_interrupted" &&
        job.value("state").toString() == "interrupted" &&
        (job.value("action").toString() == "export" || job.value("action").toString() == "compatibility");
    if (!m_preservePendingForRequest && !m_jobId.isEmpty() && (completed(job.value("state").toString()) || interruptedExport) &&
        !recoverable && !unknownOutcome) {
        const QString jobState = job.value("state").toString();
        const bool succeeded = jobState == "complete" || jobState == "completed" ||
                               jobState == "succeeded" || jobState == "done";
        // A failed task must stay visible until the user explicitly checks;
        // an automatic status read must not erase its error after 200 ms.
        const bool followUp = succeeded && !response.value("live_status").toBool();
        m_refreshLegacy = bounded(job.value("action"), 64).startsWith("legacy-");
        if (job.value("state").toString() == "completed" && job.value("action").toString() == "update") {
            m_packagePath.clear();
            m_expectedUpdateVersion.clear();
            m_expectedUpdateSha256.clear();
            m_update.clear();
        }
        m_jobId.clear();
        if (m_operationAction != "confirm-calls" || confirmedCallResponse(response) || currentCallObservation(response)) clearPendingOperation();
        m_settings.remove("pending_job");
        if (followUp && m_oneShotActive) {
            // This observation proved only the original task's completion.
            // A different client may now own the active task; never display
            // an unobserved network state or authorize a new write.
            m_settings.remove("last_observation_v1");
            m_model.clear(); m_model.insert("state", "task_complete_status_unchecked");
            m_model.insert("primary_action", "inspect");
            m_model.insert("actions", QVariantList() << QVariant("status") << QVariant("compatibility"));
            m_cachedStatus = true;
        } else if (followUp) m_refreshPending = true;
    } else if (!m_preservePendingForRequest && id.isEmpty() && m_action == "confirm-calls" &&
               !m_runtimeError && confirmedCallResponse(response)) {
        // Call confirmation is synchronous; management writes require jobs.
        clearPendingOperation();
    } else if (!m_preservePendingForRequest && id.isEmpty() && readAction(m_action) &&
               (confirmedCallResponse(response) || currentCallObservation(response))) {
        // An observation may resolve this one saved call check. It must not
        // erase an unknown install/enable/update operation or another context.
        if (currentCallObservation(response)) {
            if (response.value("call_context").toString() != m_pendingCallContext)
                m_notice = "calls_context_changed_notice";
            else if (response.value("state").toString() == "registered")
                m_notice = "calls_not_saved_notice";
            else
                m_notice = "calls_saved_notice";
        }
        clearPendingOperation();
    }
    if (response.value("ok").type() == QVariant::Bool && response.value("ok").toBool() &&
        !interruptedExport && !m_preservePendingForRequest && !m_runtimeError && m_jobId.isEmpty() && m_operationId.isEmpty() &&
        m_model.value("state").toString() != "task_complete_status_unchecked" &&
        ((readAction(m_action) && m_action != "legacy-inspect") || m_action == "confirm-calls" ||
         response.value("live_status").toBool())) saveCachedModel(response);
    if (response.value("ok").type() == QVariant::Bool && response.value("ok").toBool() &&
        !m_preservePendingForRequest && m_jobId.isEmpty() && m_operationId.isEmpty() &&
        (readAction(m_action) || response.value("live_status").toBool())) {
        const QString resultNotice = m_notice;
        refreshUpdateAvailability();
        if (resultNotice == "calls_saved_notice" || resultNotice == "calls_not_saved_notice" ||
            resultNotice == "calls_context_changed_notice") m_notice = resultNotice;
    }
    m_settings.sync();
    emit settingsChanged();
    return true;
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
    if (!m_coldPollJobId.isEmpty()) {
        const QString expected = m_coldPollJobId;
        m_coldPollJobId.clear();
        const QVariant rawJob = m_settings.value("pending_job");
        const QVariant rawOperation = m_settings.value("pending_operation");
        if (m_settings.status() != QSettings::NoError || rawJob.type() != QVariant::String ||
            rawJob.toString() != expected || m_jobId != expected ||
            (m_settings.contains("pending_operation") && rawOperation.type() != QVariant::String) ||
            (!rawOperation.toString().isEmpty() && rawOperation.toString() != expected) ||
            m_settings.value("pending_operation_action").toString() == "confirm-calls") {
            m_invalidPendingIdentity = true; m_jobId.clear(); m_operationId.clear();
            m_model.clear(); m_model.insert("state", "recovery_required");
            m_model.insert("primary_action", "compatibility");
            m_cachedStatus = true; m_allowAutoPoll = false; emit modelChanged(); return;
        }
        m_oneShotActive = true;
        invoke("poll");
        if (!m_busy) { m_oneShotActive = false; m_allowAutoPoll = false; }
        return;
    }
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
    m_pendingAction = "bundled-update";
    m_pendingExtra.clear();
    m_pollTimer.stop();
    emit confirmationNeeded();
}

void MobileController::requestAction(const QString &action)
{
    if (!allowed(action)) { fail("action_unavailable"); return; }
    if (action == "update" && !hasPackage() && !canApplyBundledUpdate()) { fail("package_invalid"); return; }
    if (action == "resume" && m_jobId.isEmpty()) { fail("operation_unknown"); return; }
    if (action == "confirm-calls" || action.startsWith("legacy-")) { fail("action_unavailable"); return; }
    if (readAction(action) || action == "export" || action == "compatibility") { invoke(action); return; }
    m_pendingAction = action;
    m_pendingExtra.clear();
    m_pollTimer.stop();
    emit confirmationNeeded();
}

QString MobileController::confirmationTitle() const
{
    const QString title = label(m_pendingAction == "download-update" ? "download_update" :
                                m_pendingAction == "bundled-update" ? "bundled_update" : m_pendingAction);
    return title.isEmpty() ? label("confirm_title") : title;
}

QString MobileController::confirmationBody() const
{
    QString text = label(m_pendingAction.startsWith("legacy-") ? "legacy_confirm" :
                         (m_pendingAction == "download-update" || m_pendingAction == "bundled-update") ? "update_confirm" : m_pendingAction + "_confirm");
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
    if (action == "bundled-update") {
        m_packagePath.clear(); m_expectedUpdateVersion.clear(); m_expectedUpdateSha256.clear();
        emit settingsChanged(); startConfirmedUpdate(); return;
    }
    if (action == "update") { startConfirmedUpdate(extra); return; }
    invoke(action, extra);
}

void MobileController::startConfirmedUpdate(const QVariantMap &extra)
{
    m_updateFeedback.clear();
    const QStringList oldUpdateNotices = QString("package_selected,checking_update,downloading_update,up_to_date,update_available,app_update_available,both_updates_available,app_update_check_service,update_check_phone").split(',');
    if (oldUpdateNotices.contains(m_notice)) m_notice.clear();
    invoke("update", extra);
    if (!m_busy && !m_error.isEmpty()) { m_updateFeedback = m_error; emit modelChanged(); }
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
    if (!canExportBackup()) { fail("action_unavailable"); return; }
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
    m_updateFeedback = "package_picker_error";
    emit modelChanged();
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
        canonical.contains('\n') || canonical.contains('\r')) {
        m_packagePath.clear(); m_expectedUpdateVersion.clear(); m_expectedUpdateSha256.clear();
        m_updateFeedback = "package_invalid"; emit settingsChanged(); emit modelChanged(); return;
    }
    m_packagePath = canonical;
    m_expectedUpdateVersion.clear();
    m_expectedUpdateSha256.clear();
    m_latest.clear(); m_update.clear();
    m_notice = "package_selected";
    m_updateFeedback = "package_selected";
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
    if (m_busy || jobRunning()) { m_updateFeedback = "wait_job"; emit modelChanged(); return; }
    m_update.clear(); m_latest.clear(); m_metadata.clear();
    m_transfer = "metadata"; m_updateFeedback = "checking_update"; m_redirects = 0; m_busy = true;
    m_transferElapsed.start();
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
    resetNetworkDeadline();
    emit modelChanged();
}

void MobileController::downloadUpdate()
{
    if (m_busy || jobRunning() || m_update.isEmpty()) return;
    if (!allowed("update")) { m_updateFeedback = "action_unavailable"; emit modelChanged(); return; }
    m_pendingAction = "download-update";
    m_pendingExtra.clear();
    m_pollTimer.stop();
    emit confirmationNeeded();
}

void MobileController::beginDownload()
{
    if (m_busy || jobRunning() || m_update.isEmpty() || !allowed("update")) { m_updateFeedback = "action_unavailable"; emit modelChanged(); return; }
    const QString filename = "/accounts/1000/shared/downloads/bb10-volte-update-" + newOperationId() + ".zip.part";
    if (QFileInfo(filename).exists() || QFileInfo(filename).isSymLink()) { m_updateFeedback = "storage_denied"; emit modelChanged(); return; }
    m_download.setFileName(filename);
    const int fd = ::open(filename.toLocal8Bit().constData(), O_WRONLY | O_CREAT | O_EXCL, 0600);
    if (fd < 0) { m_updateFeedback = "storage_denied"; emit modelChanged(); return; }
    if (!m_download.open(fd, QIODevice::WriteOnly, QFile::AutoCloseHandle)) { ::close(fd); m_updateFeedback = "storage_denied"; emit modelChanged(); return; }
    m_downloadBytes = 0; SHA256_Init(&m_downloadHash);
    m_transfer = "package"; m_updateFeedback = "downloading_update"; m_redirects = 0; m_busy = true;
    m_transferElapsed.start();
    beginNetwork(QUrl(m_update.value("package_url").toString()));
}

void MobileController::networkReady()
{
    if (!m_reply || m_reply->attribute(QNetworkRequest::RedirectionTargetAttribute).isValid()) return;
    const QByteArray bytes = m_reply->readAll();
    if (!bytes.isEmpty()) resetNetworkDeadline();
    if (m_transfer == "metadata") {
        m_metadata += bytes;
        if (m_metadata.size() > MAX_METADATA) finishNetworkError("bad_update_metadata");
    } else {
        m_downloadBytes += bytes.size();
        if (m_downloadBytes > MAX_PACKAGE || m_downloadBytes > m_update.value("size").toLongLong()) {
            finishNetworkError("package_changed"); return;
        }
        if (m_download.write(bytes) != bytes.size()) { finishNetworkError("storage_denied"); return; }
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
            !QRegExp("^[0-9]{1,5}(\\.[0-9]{1,5}){3}$").exactMatch(metadata.value("version").toString())) {
            finishNetworkError("bad_update_metadata"); return;
        }
        m_latest = metadata;
        refreshUpdateAvailability();
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
        m_packagePath = final; m_expectedUpdateVersion = m_update.value("version").toString();
        m_expectedUpdateSha256 = m_update.value("sha256").toString();
        m_busy = false; m_transfer.clear(); m_updateFeedback.clear();
        emit settingsChanged();
        // The preceding user confirmation covers download and installation; the runtime verifies the publisher signature.
        startConfirmedUpdate();
        return;
    }
    m_transfer.clear(); scheduleRefresh(); emit modelChanged();
}

void MobileController::stopNetworkTransfer()
{
    m_networkDeadline.stop();
    if (m_reply) {
        QNetworkReply *reply = m_reply; m_reply = 0;
        reply->disconnect(this); reply->abort(); reply->deleteLater();
    }
    if (m_download.isOpen()) m_download.close();
    const QString partial = m_download.fileName();
    if (m_transfer == "package" && partial.startsWith("/accounts/1000/shared/downloads/bb10-volte-update-") &&
        partial.endsWith(".zip.part") && !QFileInfo(partial).isSymLink()) QFile::remove(partial);
    m_busy = false; m_transfer.clear();
}

void MobileController::finishNetworkError(const QString &code)
{
    stopNetworkTransfer();
    m_updateFeedback = code; scheduleRefresh(); emit modelChanged();
}

void MobileController::cancelUpdateTransfer()
{
    // Once Root starts an update m_transfer has already been cleared, so this
    // button can stop only a network request and its own partial download.
    if (!networkTransferInProgress()) return;
    stopNetworkTransfer();
    m_updateFeedback = "update_transfer_cancelled";
    scheduleRefresh(); emit modelChanged();
}

void MobileController::refreshUpdateAvailability()
{
    if (m_latest.isEmpty()) return;
    const QString available = m_latest.value("version").toString();
    const bool appNewer = newerVersion(available, version());
    const QString runtime = bounded(m_model.value("details").toMap().value("version"), 40);
    const bool currentRuntimeKnown = !m_cachedStatus && m_error.isEmpty() && m_jobId.isEmpty() &&
        m_operationId.isEmpty() && QRegExp("^[0-9]{1,5}(\\.[0-9]{1,5}){3}$").exactMatch(runtime);
    m_update.clear();
    QString updateNotice;
    if (!currentRuntimeKnown) updateNotice = appNewer ? "app_update_check_service" : "update_check_phone";
    else if (newerVersion(available, runtime)) {
        m_update = m_latest;
        updateNotice = appNewer ? "both_updates_available" : "update_available";
    } else updateNotice = appNewer ? "app_update_available" : "up_to_date";
    const QStringList updateNotices = QString("checking_update,up_to_date,update_available,app_update_available,both_updates_available,app_update_check_service,update_check_phone").split(',');
    if (m_updateFeedback.isEmpty() || updateNotices.contains(m_updateFeedback)) m_updateFeedback = updateNotice;
    if (m_notice.isEmpty() || updateNotices.contains(m_notice)) m_notice = updateNotice;
}

void MobileController::resetNetworkDeadline()
{
    const qint64 total = m_transfer == "metadata" ? METADATA_TOTAL_TIMEOUT : PACKAGE_TOTAL_TIMEOUT;
    const qint64 remaining = total - m_transferElapsed.elapsed();
    m_networkDeadline.start(static_cast<int>(qMax<qint64>(1, qMin<qint64>(NETWORK_IDLE_TIMEOUT, remaining))));
}

void MobileController::networkTimeout()
{
    finishNetworkError(m_transfer == "metadata" ? "update_check_timeout" : "download_timeout");
}
