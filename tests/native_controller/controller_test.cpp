// Exercises the actual production MobileController with Qt on a disposable
// Linux container. /bin/__root is an inert fake supplied only by that image.
#include <QObject>
#include <QVariantMap>
#include <QProcess>
#include <QTimer>
#include <QSettings>
#include <QtNetwork/QNetworkAccessManager>
#include <QtNetwork/QNetworkReply>
#include <QFile>
#include <openssl/sha.h>
#define private public
#include "mobilecontroller.h"
#undef private
#include <QCoreApplication>
#include <QDir>
#include <QElapsedTimer>
#include <QJsonDocument>
#include <QJsonObject>
#include <QRegularExpression>
#include <QThread>
#include <iostream>
#include <stdexcept>

#define CHECK(value) do { if (!(value)) throw std::runtime_error(std::string(__func__) + ":" + std::to_string(__LINE__) + ": " + #value); } while (0)

static const QString ROOT = "/tmp/bb10-controller-harness";
static const QString CONTEXT(32, 'a');
static const QString JOB(32, 'b');
static const QString OPERATION(32, 'c');

static void write(const QString &path, const QByteArray &bytes)
{
    QFile f(path); CHECK(f.open(QIODevice::WriteOnly | QIODevice::Truncate));
    CHECK(f.write(bytes) == bytes.size()); f.close();
}

static QByteArray read(const QString &path)
{
    QFile f(path); if (!f.open(QIODevice::ReadOnly)) return QByteArray();
    return f.readAll();
}

static void response(const QVariantMap &value)
{
    write(ROOT + "/response.json", QJsonDocument::fromVariant(value).toJson(QJsonDocument::Compact));
}

static void spin(int ms)
{
    QElapsedTimer timer; timer.start();
    while (timer.elapsed() < ms) { QCoreApplication::processEvents(QEventLoop::AllEvents, 20); QThread::msleep(5); }
}

static void waitForFile(const QString &path)
{
    QElapsedTimer timer; timer.start();
    while (!QFile::exists(path) && timer.elapsed() < 5000) spin(20);
    CHECK(QFile::exists(path));
}

static void finish(MobileController &controller)
{
    QElapsedTimer timer; timer.start();
    while (controller.busy() && timer.elapsed() < 5000) { QCoreApplication::processEvents(QEventLoop::AllEvents, 20); QThread::msleep(5); }
    CHECK(!controller.busy());
    spin(50);
}

static int calls() { return read(ROOT + "/calls").count('\n'); }

static QVariantMap registered()
{
    QVariantMap device; device.insert("variant", "SQN100-3"); device.insert("os_version", "10.3.3.3216");
    QVariantMap details; details.insert("device", device); details.insert("carrier", "telecom");
    details.insert("phase", "running"); details.insert("version", "0.1.0.15");
    QVariantMap result; result.insert("schema", 2); result.insert("ok", true); result.insert("state", "registered");
    result.insert("primary_action", "confirm-calls");
    result.insert("actions", QVariantList() << "status" << "disable" << "export" << "compatibility" << "uninstall" << "confirm-calls");
    result.insert("details", details); result.insert("call_context", CONTEXT); return result;
}

static QVariantMap requestFromCommand(const QString &action)
{
    const QString command = QString::fromUtf8(read(ROOT + "/last-command"));
    QRegularExpression rx("'" + action + "' '([A-Za-z0-9+/=]+)'");
    const QRegularExpressionMatch match = rx.match(command); CHECK(match.hasMatch());
    const QJsonDocument doc = QJsonDocument::fromJson(QByteArray::fromBase64(match.captured(1).toLatin1()));
    CHECK(doc.isObject()); return doc.object().toVariantMap();
}

static void settingsClearPending()
{
    QSettings settings; settings.remove("pending_job"); settings.remove("pending_operation");
    settings.remove("pending_operation_action"); settings.remove("pending_call_context"); settings.sync();
    CHECK(settings.status() == QSettings::NoError);
}

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    QCoreApplication::setOrganizationName("BB10ControllerHarness");
    QCoreApplication::setApplicationName("IsolatedCacheTests");
    QSettings::setDefaultFormat(QSettings::IniFormat);
    QSettings::setPath(QSettings::IniFormat, QSettings::UserScope, ROOT + "/settings");
    try {
        if (argc == 2 && QByteArray(argv[1]) == "cold-read") {
            QObject parent; const int before = calls();
            MobileController c(&parent); c.initialize();
            CHECK(c.m_cachedStatus && c.primaryAction() == "confirm-calls");
            spin(350); CHECK(calls() == before);
            std::cout << "PASS: cache survives an actual process restart without a status request" << std::endl;
            return 0;
        }
        CHECK(QDir().mkpath(ROOT + "/working/app/native/assets/runtime"));
        QFile::remove(ROOT + "/working/app/native/assets/runtime/entry.py");
        CHECK(QFile::copy("/work/mobile/runtime/entry.py", ROOT + "/working/app/native/assets/runtime/entry.py"));
        CHECK(QDir::setCurrent(ROOT + "/working"));
        QSettings().clear(); QFile::remove(ROOT + "/calls");
        QObject parent;
        {
            CHECK(MobileController::requestTimeoutForElapsed(0) == 150000);
            CHECK(MobileController::requestTimeoutForElapsed(899000) == 1000);
            CHECK(MobileController::requestTimeoutForElapsed(900000) == 1);
            response(registered()); write(ROOT + "/progress", "1");
            MobileController c(&parent); c.initialize(); c.refresh();
            waitForFile(ROOT + "/progress-started"); c.m_deadline.start(25000);
            QElapsedTimer partial; partial.start();
            while (c.busy() && !c.m_output.contains("noise\nBB10_PRO") && partial.elapsed() < 5000) spin(20);
            CHECK(c.m_output.contains("noise\nBB10_PRO") && c.m_deadline.interval() == 25000);
            write(ROOT + "/progress-release", "1");
            QElapsedTimer wait; wait.start();
            while (c.busy() && c.m_deadline.interval() != 150000 && wait.elapsed() < 5000) spin(20);
            CHECK(c.busy() && c.m_deadline.interval() == 150000);
            write(ROOT + "/progress-finish", "1");
            finish(c); QFile::remove(ROOT + "/progress");
            QFile::remove(ROOT + "/progress-started"); QFile::remove(ROOT + "/progress-release"); QFile::remove(ROOT + "/progress-finish");
            CHECK(c.model().value("state").toString() == "registered");
            QSettings().clear(); QFile::remove(ROOT + "/calls");
        }
        {
            response(registered()); write(ROOT + "/noise", "1");
            MobileController c(&parent); c.initialize(); c.refresh();
            waitForFile(ROOT + "/noise-started"); c.m_deadline.start(25000);
            write(ROOT + "/noise-release", "1");
            QElapsedTimer wait; wait.start();
            while (c.busy() && !c.m_output.contains("BB10_PROGRESS:2\nnoise\n") && wait.elapsed() < 5000) spin(20);
            CHECK(c.m_output.contains("BB10_PROGRESS:2\nnoise\n"));
            CHECK(c.busy() && c.m_deadline.interval() == 25000);
            write(ROOT + "/noise-finish", "1");
            finish(c); QFile::remove(ROOT + "/noise");
            QFile::remove(ROOT + "/noise-started"); QFile::remove(ROOT + "/noise-release"); QFile::remove(ROOT + "/noise-finish");
            QSettings().clear(); QFile::remove(ROOT + "/calls");
        }
        {
            MobileController c(&parent); c.initialize();
            CHECK(c.model().value("state").toString() == "not_checked");
            CHECK(!c.m_allowAutoPoll && !c.m_pollTimer.isActive());
            c.enteredBackground(); c.enteredForeground(); c.screenAsleep(); c.screenAwake();
            spin(350); CHECK(calls() == 0); CHECK(!c.m_pollTimer.isActive());
            response(registered());
            c.refresh(); CHECK(c.m_deadline.interval() == 150000);
            finish(c); CHECK(calls() == 1);
            CHECK(c.model().value("state").toString() == "registered");
            CHECK(!c.m_cachedStatus && c.allowed("confirm-calls"));
            CHECK(QSettings().contains("last_observation_v1"));
        }
        CHECK(QProcess::execute(QCoreApplication::applicationFilePath(), QStringList() << "cold-read") == 0);
        {
            MobileController c(&parent); c.initialize();
            CHECK(c.m_cachedStatus && c.primaryAction() == "confirm-calls");
            CHECK(c.allowed("confirm-calls") && !c.allowed("disable") && !c.allowed("uninstall"));
            c.setLanguage("zh");
            CHECK(c.cachedStatusText().contains(QString::fromUtf8("上次")));
            CHECK(c.statusTitle().startsWith(QString::fromUtf8("上次检查")));
            CHECK(c.allowed("export") && !c.canExportBackup());
            c.setLanguage("en"); CHECK(c.cachedStatusText().contains("last checked"));
            int notifications = 0;
            QObject::connect(&c, &MobileController::modelChanged, [&notifications]() { ++notifications; });
            c.setExperimentalVisible(true); c.setExperimentalVisible(false); CHECK(notifications > 0);
            c.enteredBackground(); c.enteredForeground(); c.screenAsleep(); c.screenAwake();
            spin(350); CHECK(calls() == 1); CHECK(!c.m_pollTimer.isActive());
        }
        {
            MobileController c(&parent); c.initialize();
            c.m_cachedStatus = true;
            const QStringList states = QString("ready_to_install,update_ready,disabled").split(',');
            for (const QString &state : states) {
                c.m_model.insert("state", state);
                CHECK(c.statusMessage() == c.label("cached_general_help"));
            }
        }
        {
            QSettings settings; settings.setValue("pending_job", JOB);
            settings.setValue("pending_operation", OPERATION); settings.setValue("pending_operation_action", "enable"); settings.sync();
            MobileController c(&parent); c.initialize();
            CHECK(c.model().value("state").toString() == "recovery_required");
            CHECK(c.primaryAction() == "compatibility" && !c.operationInProgress());
            CHECK(!c.allowed("confirm-calls")); spin(350); CHECK(calls() == 1);
            QVariantMap job; job.insert("id", JOB); job.insert("state", "waiting_reboot"); job.insert("action", "enable");
            QVariantMap r; r.insert("schema", 2); r.insert("ok", true); r.insert("state", "reboot_required");
            r.insert("primary_action", "resume"); r.insert("actions", QVariantList() << "resume" << "compatibility");
            r.insert("job_id", JOB); r.insert("job", job); response(r);
            c.primary(); finish(c); CHECK(calls() == 2);
            CHECK(!requestFromCommand("compatibility").contains("job_id"));
            CHECK(QSettings().value("pending_job").toString() == JOB);
            CHECK(QSettings().value("pending_operation").toString() == OPERATION);
            CHECK(!c.m_pollTimer.isActive());
        }
        {
            QSettings settings; settings.remove("pending_job"); settings.setValue("pending_operation", OPERATION);
            settings.setValue("pending_operation_action", "enable"); settings.sync();
            MobileController c(&parent); c.initialize(); CHECK(!c.allowed("confirm-calls"));
            CHECK(c.allowed("compatibility") && !c.canExportBackup());
            QVariantMap exported; exported.insert("schema", 2); exported.insert("ok", true); exported.insert("state", "exported");
            exported.insert("primary_action", "status"); exported.insert("actions", QVariantList() << "status" << "compatibility");
            response(exported); c.requestAction("compatibility"); finish(c);
            CHECK(calls() == 3); CHECK(c.m_operationId == OPERATION);
            CHECK(QSettings().value("pending_operation").toString() == OPERATION);
            const QString reportId = requestFromCommand("compatibility").value("operation_id").toString();
            CHECK(reportId.size() == 32 && reportId != OPERATION);
            CHECK(!c.allowed("confirm-calls"));
        }
        {
            // A failed probe must not replace a usable cached observation with
            // a false unsupported state or erase the call-check entry.
            settingsClearPending();
            MobileController c(&parent); c.initialize(); CHECK(c.m_cachedStatus);
            QVariantMap error; error.insert("code", "preflight_or_recovery_check_failed");
            QVariantMap r; r.insert("schema", 2); r.insert("ok", false); r.insert("state", "error"); r.insert("error", error);
            response(r); c.refresh(); finish(c);
            CHECK(c.m_cachedStatus && c.model().value("state").toString() == "registered");
            CHECK(c.m_notice == "inspection_unavailable" && c.allowed("confirm-calls"));
        }
        {
            // A real pending read is presented as checking in both languages,
            // while its previous observation remains marked as cached.
            settingsClearPending(); MobileController c(&parent); c.initialize();
            write(ROOT + "/hang", "1"); c.refresh(); spin(100); CHECK(c.busy());
            c.setLanguage("zh"); CHECK(c.statusTitle() == c.label("checking"));
            CHECK(c.statusMessage() == c.label("checking_help"));
            CHECK(c.cachedStatusText() == c.label("previous_status_refreshing"));
            c.setLanguage("en"); CHECK(c.statusTitle() == "Checking your phone");
            CHECK(c.activityVisible() && !c.cachedStatusText().isEmpty());
            c.m_cachedStatus = false;
            CHECK(c.cachedStatusText() == c.label("previous_status_refreshing"));
            c.m_model.insert("state", "not_checked"); CHECK(c.cachedStatusText().isEmpty());
            c.processTimeout(); finish(c); QFile::remove(ROOT + "/hang");
            CHECK(!c.activityVisible());
        }
        {
            // Unknown committed outcomes remain attached even if the old job
            // state is called failed/interrupted. Reopening may only check it.
            const QStringList states = QString("failed,interrupted").split(',');
            for (int i = 0; i < states.size(); ++i) {
                settingsClearPending(); QSettings settings;
                settings.setValue("pending_operation", OPERATION); settings.setValue("pending_operation_action", "enable"); settings.sync();
                MobileController c(&parent); c.initialize();
                QVariantMap job; job.insert("id", OPERATION); job.insert("action", "enable"); job.insert("state", states.at(i));
                QVariantMap r; r.insert("schema", 2); r.insert("ok", true); r.insert("state", "job_outcome_unknown");
                r.insert("job_id", OPERATION); r.insert("job", job); r.insert("primary_action", "poll");
                r.insert("actions", QVariantList() << "poll" << "compatibility");
                response(r); c.refresh(); finish(c);
                CHECK(c.m_operationId == OPERATION && c.m_jobId == OPERATION);
                CHECK(QSettings().value("pending_job").toString() == OPERATION && !c.allowed("enable"));
                MobileController reopened(&parent); reopened.initialize();
                CHECK(reopened.m_operationId == OPERATION && reopened.m_jobId == OPERATION);
                CHECK(reopened.primaryAction() == "poll" && !reopened.allowed("enable"));
                response(r); reopened.primary(); finish(reopened);
                CHECK(reopened.m_operationId == OPERATION && reopened.m_jobId == OPERATION);
            }
            settingsClearPending();
        }
        {
            // A failed update remains visible rather than being replaced by
            // a successful status response from an unsolicited follow-up.
            settingsClearPending(); QSettings settings;
            settings.setValue("pending_job", OPERATION); settings.setValue("pending_operation", OPERATION);
            settings.setValue("pending_operation_action", "update"); settings.sync();
            MobileController c(&parent); c.initialize();
            QVariantMap job; job.insert("id", OPERATION); job.insert("action", "update");
            job.insert("state", "failed"); job.insert("error_code", "update_version_mismatch");
            QVariantMap r; r.insert("schema", 2); r.insert("ok", false); r.insert("state", "error");
            r.insert("job_id", OPERATION); r.insert("job", job); r.insert("primary_action", "status");
            r.insert("actions", QVariantList() << "status" << "compatibility");
            response(r); c.primary(); finish(c); const int after = calls(); spin(350);
            CHECK(calls() == after && !c.m_pollTimer.isActive());
            CHECK(c.m_error == "update_version_mismatch" && c.statusMessage() == c.label("update_version_mismatch"));
            CHECK(c.updateFeedback() == c.label("update_version_mismatch"));
            c.enteredBackground(); c.enteredForeground(); spin(250); CHECK(calls() == after);
            settingsClearPending();
        }
        {
            // FailedToStart while checking a pending update is still an update
            // feedback, and it must not erase the original operation identity.
            for (int i = 0; i < 2; ++i) {
                settingsClearPending(); QSettings settings;
                settings.setValue("pending_operation", OPERATION);
                settings.setValue("pending_operation_action", "update");
                if (i == 0) settings.setValue("pending_job", OPERATION);
                settings.sync();
                MobileController c(&parent); c.initialize();
                c.m_process.setWorkingDirectory(ROOT + "/does-not-exist");
                const int before = calls(); c.primary(); finish(c);
                CHECK(calls() == before && c.m_operationId == OPERATION);
                CHECK(c.updateFeedback() == c.label("root_not_ready"));
            }
            settingsClearPending();
        }
        {
            // A later matching observation replaces the stale unknown update
            // feedback with the current task status, without starting again.
            settingsClearPending(); QSettings settings;
            settings.setValue("pending_operation", OPERATION); settings.setValue("pending_job", OPERATION);
            settings.setValue("pending_operation_action", "update"); settings.sync();
            MobileController c(&parent); c.initialize(); c.m_updateFeedback = "operation_unknown";
            QVariantMap job; job.insert("id", OPERATION); job.insert("action", "update"); job.insert("state", "waiting_reboot");
            QVariantMap r; r.insert("schema", 2); r.insert("ok", true); r.insert("state", "reboot_required");
            r.insert("job_id", OPERATION); r.insert("job", job); r.insert("primary_action", "poll");
            r.insert("actions", QVariantList() << "poll" << "compatibility");
            response(r); const int before = calls(); c.primary(); finish(c);
            CHECK(calls() == before + 1 && c.m_jobId == OPERATION && c.m_updateFeedback.isEmpty());
            settingsClearPending();
        }
        {
            // A successful-looking reply without the asynchronous job ID
            // cannot settle any management write or permit a duplicate.
            const QStringList actions = QString("install,enable,disable,update,rollback,uninstall,export").split(',');
            for (int i = 0; i < actions.size(); ++i) {
                settingsClearPending(); MobileController c(&parent); c.m_cachedStatus = false;
                c.m_model.insert("state", "disabled"); c.m_model.insert("actions", QVariantList() << actions.at(i));
                QVariantMap extra; if (actions.at(i) == "export") extra.insert("export_kind", "backup");
                QVariantMap noJob; noJob.insert("schema", 2); noJob.insert("ok", true); noJob.insert("state", "waiting");
                response(noJob); const int before = calls(); c.invoke(actions.at(i), extra); finish(c); spin(250);
                CHECK(calls() == before + 1 && !c.m_operationId.isEmpty());
                CHECK(c.m_error == "operation_unknown" && c.m_model.value("state").toString() == "disabled");
                CHECK(QSettings().value("pending_operation").toString() == c.m_operationId);
                CHECK(actions.at(i) == "export" ? !c.canExportBackup() : !c.allowed(actions.at(i)));
            }
            settingsClearPending();
        }
        {
            // An identified unknown job cannot be settled by another job's
            // success, nor can that response erase the update warning.
            settingsClearPending(); QSettings settings;
            settings.setValue("pending_operation", OPERATION); settings.setValue("pending_job", OPERATION);
            settings.setValue("pending_operation_action", "update"); settings.sync();
            MobileController c(&parent); c.initialize(); c.m_model.insert("state", "job_outcome_unknown");
            c.m_updateFeedback = "operation_unknown";
            QVariantMap job; job.insert("id", JOB); job.insert("action", "update"); job.insert("state", "completed");
            QVariantMap other; other.insert("schema", 2); other.insert("ok", true); other.insert("state", "waiting");
            other.insert("job_id", JOB); other.insert("job", job); response(other);
            c.invoke("poll"); finish(c);
            CHECK(c.m_operationId == OPERATION && c.m_jobId == OPERATION && c.m_updateFeedback == "operation_unknown");
            CHECK(c.m_model.value("state").toString() == "job_outcome_unknown");
            settingsClearPending();
        }
        {
            // A matching ID alone cannot settle a job when success is absent,
            // malformed or contradicts the terminal journal state.
            for (int i = 0; i < 4; ++i) {
                settingsClearPending(); QSettings settings;
                settings.setValue("pending_operation", OPERATION); settings.setValue("pending_job", OPERATION);
                settings.setValue("pending_operation_action", "update"); settings.sync();
                MobileController c(&parent); c.initialize(); c.m_updateFeedback = "operation_unknown";
                QVariantMap job; job.insert("id", OPERATION); job.insert("action", "update");
                job.insert("state", i == 3 ? "failed" : "completed");
                QVariantMap r; r.insert("schema", 2); r.insert("state", "waiting");
                r.insert("job_id", OPERATION); r.insert("job", job);
                if (i == 1) r.insert("ok", "true");
                if (i == 2) { r.insert("ok", false); r.insert("live_status", true); }
                if (i == 3) r.insert("ok", true);
                response(r); c.invoke("poll"); finish(c);
                CHECK(c.m_operationId == OPERATION && c.m_jobId == OPERATION);
                CHECK(c.m_error == "operation_unknown" && c.m_updateFeedback == "operation_unknown");
                CHECK(!c.allowed("update"));
            }
            settingsClearPending();
        }
        {
            // Older app versions stored an operation ID without an action.
            // Query that exact ID; a generic healthy state cannot settle it.
            settingsClearPending(); QSettings settings;
            settings.setValue("pending_operation", OPERATION); settings.sync();
            MobileController c(&parent); c.initialize();
            CHECK(c.m_operationAction.isEmpty() && c.m_operationId == OPERATION);
            response(registered()); c.refresh(); finish(c);
            const QVariantMap sent = requestFromCommand("inspect");
            CHECK(sent.value("job_id").toString() == OPERATION && sent.value("operation_id").toString() == OPERATION);
            CHECK(c.m_operationId == OPERATION && c.m_error == "operation_unknown" && !c.allowed("enable"));
            QVariantMap job; job.insert("id", OPERATION); job.insert("action", "enable"); job.insert("state", "completed");
            QVariantMap r; r.insert("schema", 2); r.insert("ok", true); r.insert("state", "waiting");
            r.insert("job_id", OPERATION); r.insert("job", job); r.insert("live_status", true);
            r.insert("primary_action", "status"); r.insert("actions", QVariantList() << "status");
            response(r); c.refresh(); finish(c);
            CHECK(c.m_operationId.isEmpty() && c.m_jobId.isEmpty());
            settingsClearPending();
        }
        {
            // The durable update can finish while its separate live phone
            // probe fails. Resolve the matching job but keep the probe error.
            settingsClearPending(); QSettings settings;
            settings.setValue("pending_operation", OPERATION); settings.setValue("pending_job", OPERATION);
            settings.setValue("pending_operation_action", "update"); settings.sync();
            MobileController c(&parent); c.initialize();
            QVariantMap job; job.insert("id", OPERATION); job.insert("action", "update"); job.insert("state", "completed");
            QVariantMap error; error.insert("code", "request_timeout");
            QVariantMap r; r.insert("schema", 2); r.insert("ok", false); r.insert("state", "error");
            r.insert("job_id", OPERATION); r.insert("job", job); r.insert("live_status", true); r.insert("error", error);
            response(r); c.invoke("poll"); finish(c);
            CHECK(c.m_operationId.isEmpty() && c.m_jobId.isEmpty() && c.m_error == "request_timeout");
            CHECK(c.statusTitle() == c.label("task_completed_status_unavailable"));
            CHECK(c.statusMessage() == c.label("request_timeout") && c.updateFeedback().contains(c.label("request_timeout")));
            CHECK(c.updateFeedback().contains(c.label("task_completed_status_unavailable")));
            settingsClearPending();
        }
        {
            // Only explicit pre-dispatch rejection clears a freshly-created
            // ID; rejecting resume always preserves its existing identity.
            const QStringList reasons = QString("runtime_selection_changed,bridge_bundle_changed,unsafe_bridge_entry").split(',');
            for (int i = 0; i < reasons.size(); ++i) {
                settingsClearPending(); MobileController c(&parent); c.m_cachedStatus = false;
                c.m_model.insert("state", "disabled"); c.m_model.insert("actions", QVariantList() << "enable");
                QVariantMap error; error.insert("code", reasons.at(i));
                QVariantMap r; r.insert("schema", 2); r.insert("ok", false); r.insert("state", "error"); r.insert("error", error);
                response(r); c.invoke("enable"); finish(c);
                CHECK(c.m_operationId.isEmpty() && !QSettings().contains("pending_operation"));
            }
            settingsClearPending(); QSettings settings;
            settings.setValue("pending_operation", OPERATION); settings.setValue("pending_job", OPERATION);
            settings.setValue("pending_operation_action", "update"); settings.sync();
            MobileController c(&parent); c.initialize();
            c.m_cachedStatus = false;
            c.m_model.insert("primary_action", "resume"); c.m_model.insert("actions", QVariantList() << "resume");
            QVariantMap error; error.insert("code", "runtime_selection_changed");
            QVariantMap r; r.insert("schema", 2); r.insert("ok", false); r.insert("state", "error"); r.insert("error", error);
            response(r); c.invoke("resume"); finish(c);
            CHECK(c.m_operationId == OPERATION && c.m_jobId == OPERATION && !c.allowed("update"));
            settingsClearPending();
        }
        {
            // Unknown writes lead directly to a diagnostic report, which must
            // not replace the original task state or its persistent identity.
            settingsClearPending(); QSettings settings;
            settings.setValue("pending_job", OPERATION); settings.setValue("pending_operation", OPERATION);
            settings.setValue("pending_operation_action", "enable"); settings.sync();
            MobileController c(&parent); c.initialize();
            QVariantMap job; job.insert("id", OPERATION); job.insert("action", "enable"); job.insert("state", "interrupted");
            QVariantMap pending; pending.insert("schema", 2); pending.insert("ok", true); pending.insert("state", "job_outcome_unknown");
            pending.insert("job_id", OPERATION); pending.insert("job", job); pending.insert("primary_action", "export");
            pending.insert("actions", QVariantList() << "poll" << "export" << "compatibility");
            response(pending); c.refresh(); finish(c); CHECK(c.primaryAction() == "export");
            CHECK(c.jobText().isEmpty());
            write(ROOT + "/hang", "1"); c.primary(); spin(100);
            CHECK(c.statusTitle() == c.label("report_exporting") && c.statusMessage() == c.label("report_exporting_help"));
            c.processTimeout(); finish(c); QFile::remove(ROOT + "/hang");
            CHECK(c.model().value("state").toString() == "job_outcome_unknown" && c.primaryAction() == "export");
            CHECK(c.m_notice == "report_unknown" && c.m_error.isEmpty() && c.jobText().isEmpty());
            QVariantMap bad; bad.insert("schema", 2); bad.insert("ok", true); bad.insert("state", "exported");
            QVariantMap badDetails; badDetails.insert("path", "/tmp/not-shared"); bad.insert("details", badDetails);
            response(bad); c.primary(); finish(c);
            CHECK(c.model().value("state").toString() == "job_outcome_unknown" && c.primaryAction() == "export");
            CHECK(c.m_notice == "report_unknown" && c.m_operationId == OPERATION);
            QVariantMap readError; QVariantMap reason; reason.insert("code", "root_not_ready");
            readError.insert("schema", 2); readError.insert("ok", false); readError.insert("state", "error"); readError.insert("error", reason);
            response(readError); c.refresh(); finish(c);
            CHECK(c.model().value("state").toString() == "job_outcome_unknown" && c.primaryAction() == "export");
            CHECK(c.m_notice == "root_not_ready" && c.m_jobId == OPERATION);
            QVariantMap noIdentity; noIdentity.insert("schema", 2); noIdentity.insert("ok", true); noIdentity.insert("state", "recovery_required");
            response(noIdentity); c.refresh(); finish(c);
            CHECK(c.model().value("state").toString() == "job_outcome_unknown" && c.primaryAction() == "export");
            CHECK(c.m_notice == "operation_unknown" && c.m_operationId == OPERATION);
            QVariantMap oldReply = pending; oldReply.insert("state", "recovery_required");
            oldReply.insert("primary_action", "resume"); oldReply.insert("actions", QVariantList() << "resume");
            response(oldReply); c.refresh(); finish(c);
            CHECK(c.model().value("state").toString() == "job_outcome_unknown" && c.primaryAction() == "export");
            CHECK(!c.allowed("resume") && c.m_operationId == OPERATION);
            c.m_process.setWorkingDirectory(ROOT + "/does-not-exist"); c.primary(); finish(c);
            CHECK(c.model().value("state").toString() == "job_outcome_unknown" && c.primaryAction() == "export");
            CHECK(c.m_notice == "root_not_ready" && c.m_error.isEmpty() && c.m_jobId == OPERATION);
            c.m_process.setWorkingDirectory(QString());
            write(ROOT + "/report-wait", "1"); c.primary(); spin(100);
            const QString reportId = requestFromCommand("export").value("operation_id").toString();
            CHECK(reportId.size() == 32 && reportId != OPERATION);
            CHECK(requestFromCommand("export").value("job_id").toString() == OPERATION);
            QVariantMap details; details.insert("path", "/accounts/1000/shared/documents/BB10-VoLTE/" + reportId);
            QVariantMap report; report.insert("schema", 2); report.insert("ok", true); report.insert("state", "exported");
            report.insert("details", details); response(report); write(ROOT + "/report-ready", "1"); finish(c);
            QFile::remove(ROOT + "/report-wait"); QFile::remove(ROOT + "/report-ready");
            CHECK(c.m_operationId == OPERATION && c.m_jobId == OPERATION);
            CHECK(c.model().value("state").toString() == "job_outcome_unknown");
            CHECK(c.notice() == c.label("report_exported") && c.exportPath() == details.value("path").toString());
            CHECK(!c.allowed("enable")); settingsClearPending();
        }
        {
            // A safely refused component rollback still offers diagnostics,
            // without making another service write available.
            settingsClearPending(); QSettings settings;
            settings.setValue("pending_job", OPERATION); settings.setValue("pending_operation", OPERATION);
            settings.setValue("pending_operation_action", "rollback"); settings.sync();
            MobileController c(&parent); c.initialize();
            QVariantMap job; job.insert("id", OPERATION); job.insert("action", "rollback"); job.insert("state", "failed");
            job.insert("error_code", "rollback_component_too_old");
            QVariantMap r; r.insert("schema", 2); r.insert("ok", false); r.insert("state", "error");
            r.insert("job_id", OPERATION); r.insert("job", job); r.insert("primary_action", "status");
            r.insert("actions", QVariantList() << "status" << "export" << "compatibility");
            response(r); c.primary(); finish(c);
            CHECK(c.m_error == "rollback_component_too_old" && c.allowed("export"));
            CHECK(!c.allowed("enable") && !c.allowed("rollback"));
            QVariantMap done; done.insert("schema", 2); done.insert("ok", true); done.insert("state", "exported");
            response(done); c.requestAction("export"); finish(c);
            CHECK(requestFromCommand("export").value("job_id").toString() == OPERATION);
            settingsClearPending();
        }
        {
            // Conflicting pending IDs never select another client's task for
            // a report; Root will return task=not_requested instead.
            settingsClearPending(); QSettings settings;
            settings.setValue("pending_job", JOB); settings.setValue("pending_operation", OPERATION);
            settings.setValue("pending_operation_action", "enable"); settings.sync();
            MobileController c(&parent); c.initialize();
            QVariantMap error; error.insert("code", "backup_location_unavailable");
            QVariantMap r; r.insert("schema", 2); r.insert("ok", false); r.insert("state", "error"); r.insert("error", error);
            response(r); c.requestAction("export"); finish(c);
            CHECK(!requestFromCommand("export").contains("job_id"));
            CHECK(QSettings().value("pending_job").toString() == JOB);
            CHECK(QSettings().value("pending_operation").toString() == OPERATION); settingsClearPending();
        }
        {
            // An interrupted backup is no longer a pending device write. Its
            // exact ID must match, and the user sees the export guidance.
            settingsClearPending(); QSettings settings;
            const QVariant cacheBefore = settings.value("last_observation_v1"); CHECK(cacheBefore.isValid());
            settings.setValue("pending_job", OPERATION); settings.setValue("pending_operation", OPERATION);
            settings.setValue("pending_operation_action", "backup-export"); settings.sync();
            MobileController c(&parent); c.initialize();
            QVariantMap job; job.insert("id", OPERATION); job.insert("action", "export"); job.insert("state", "interrupted");
            QVariantMap r; r.insert("schema", 2); r.insert("ok", true); r.insert("state", "export_interrupted");
            r.insert("job_id", OPERATION); r.insert("job", job); r.insert("primary_action", "status");
            r.insert("actions", QVariantList() << "status" << "compatibility");
            response(r); c.primary(); finish(c);
            CHECK(c.m_operationId.isEmpty() && c.m_jobId.isEmpty());
            CHECK(c.model().value("state").toString() == "export_interrupted");
            CHECK(c.jobText().isEmpty());
            MobileController reopened(&parent); reopened.initialize();
            CHECK(reopened.m_operationId.isEmpty() && reopened.m_jobId.isEmpty());
            CHECK(reopened.m_cachedStatus && QSettings().value("last_observation_v1") == cacheBefore);
            CHECK(reopened.model().value("state").toString() == cacheBefore.toMap().value("state").toString());
            settingsClearPending();
        }
        {
            // The actual Root request binds downloaded bytes and metadata;
            // an old-runtime rejection can clear only this fresh operation.
            settingsClearPending(); MobileController c(&parent);
            c.m_model.insert("state", "disabled"); c.m_model.insert("actions", QVariantList() << "update");
            c.m_cachedStatus = false; c.m_packagePath = "/accounts/1000/shared/downloads/update.zip";
            c.m_expectedUpdateVersion = "0.1.0.17"; c.m_expectedUpdateSha256 = QString(64, 'a');
            QVariantMap error; error.insert("code", "update_runtime_upgrade_required");
            QVariantMap r; r.insert("schema", 2); r.insert("ok", false); r.insert("state", "error"); r.insert("error", error);
            response(r); c.invoke("update"); finish(c);
            const QVariantMap sent = requestFromCommand("update");
            CHECK(sent.value("expected_version").toString() == "0.1.0.17");
            CHECK(sent.value("expected_sha256").toString() == QString(64, 'a'));
            CHECK(c.m_operationId.isEmpty() && !QSettings().contains("pending_operation"));
            CHECK(c.m_error == "update_runtime_upgrade_required");
        }
        {
            // A lost poll does not keep a stale running-job spinner alive;
            // the original identity remains protected for an explicit check.
            settingsClearPending(); QSettings settings; settings.setValue("pending_job", JOB); settings.sync();
            MobileController c(&parent); c.initialize();
            QVariantMap job; job.insert("id", JOB); job.insert("action", "enable"); job.insert("state", "running");
            c.m_model.insert("job", job); c.m_model.insert("state", "working");
            c.m_cachedStatus = false; c.m_allowAutoPoll = true;
            CHECK(c.activityVisible()); write(ROOT + "/hang", "1"); c.invoke("poll"); spin(100);
            CHECK(c.statusTitle() == c.label("checking_task"));
            c.processTimeout(); finish(c); QFile::remove(ROOT + "/hang");
            CHECK(c.jobRunning() && !c.activityVisible() && !c.m_pollTimer.isActive());
            CHECK(c.jobText().isEmpty());
            CHECK(c.m_jobId == JOB && !c.allowed("enable"));
            settingsClearPending();
        }
        {
            // Only original-backup export has blocking task progress. A
            // synchronous diagnostics export never impersonates that job.
            MobileController c(&parent); c.m_busy = true; c.m_action = "export";
            c.m_operationAction = "backup-export"; CHECK(c.operationInProgress());
            c.m_preservePendingForRequest = true; CHECK(!c.operationInProgress());
            c.m_busy = false; c.m_preservePendingForRequest = false;
            QVariantMap job; job.insert("action", "export"); job.insert("state", "running");
            c.m_model.insert("job", job); c.m_allowAutoPoll = true; CHECK(c.operationInProgress());
            c.m_allowAutoPoll = false; CHECK(!c.operationInProgress());
            c.m_allowAutoPoll = true;
            c.m_error = "request_timeout"; CHECK(!c.operationInProgress());
        }
        {
            // A found update explains why it cannot yet be installed.
            MobileController c(&parent); c.initialize(); c.m_update.insert("version", "0.1.0.99");
            CHECK(c.updateBlockMessage() == c.label("update_blocked_cached"));
            c.m_operationId = OPERATION; CHECK(c.updateBlockMessage() == c.label("update_blocked_pending"));
            c.m_operationId.clear(); c.m_cachedStatus = false; c.m_model.insert("actions", QVariantList() << "status");
            CHECK(c.updateBlockMessage() == c.label("update_blocked_state"));
            c.m_model.insert("actions", QVariantList() << "update"); CHECK(c.updateBlockMessage().isEmpty());
        }
        {
            // A cached reboot prompt is not presented as a freshly verified
            // instruction after returning from the background or lock screen.
            MobileController c(&parent); c.m_model.insert("state", "reboot_required");
            c.m_model.insert("primary_action", "poll"); c.m_jobId = JOB; c.m_cachedStatus = true;
            c.setLanguage("zh"); CHECK(c.statusTitle() == c.label("job_pending"));
            CHECK(c.statusMessage() == c.label("operation_unknown") && c.primaryAction() == "poll");
            c.setLanguage("en"); CHECK(c.statusTitle() == "Check the existing task");
        }
        {
            // A failed but recoverable job discovered from Root must override
            // an older cached registered state, even with no local pending ID.
            for (int i = 0; i < 2; ++i) {
                settingsClearPending(); MobileController c(&parent); c.m_model = registered();
                c.saveCachedModel(registered()); c.m_cachedStatus = true;
                const QString errorCode = i == 0 ? "backup_location_unavailable" : "update_version_mismatch";
                QVariantMap job; job.insert("id", OPERATION); job.insert("action", i == 0 ? "install" : "update");
                job.insert("state", "failed"); job.insert("error_code", errorCode);
                QVariantMap r; r.insert("schema", 2); r.insert("ok", false); r.insert("state", "recovery_required");
                r.insert("job_id", OPERATION); r.insert("job", job); r.insert("primary_action", "resume");
                r.insert("actions", QVariantList() << "resume" << "compatibility");
                response(r); c.refresh(); finish(c);
                CHECK(c.m_jobId == OPERATION && c.model().value("state").toString() == "recovery_required");
                CHECK(c.primaryAction() == "resume" && c.allowed("resume") && !c.allowed("confirm-calls"));
                CHECK(QSettings().value("pending_job").toString() == OPERATION);
                CHECK(i == 0 ? c.updateFeedback().isEmpty() : c.updateFeedback() == c.label(errorCode));
            }
            settingsClearPending();
        }
        {
            // Cancelling a bundled-update confirmation keeps an already chosen
            // offline package; confirming uses the bundled package instead.
            settingsClearPending(); MobileController c(&parent); c.m_cachedStatus = false;
            QVariantMap details; details.insert("bundled_update_available", true);
            c.m_model.insert("details", details); c.m_model.insert("actions", QVariantList() << "update");
            c.m_packagePath = "/previous/update.zip"; c.m_expectedUpdateVersion = "0.1.0.18";
            c.m_expectedUpdateSha256 = QString(64, 'a'); c.m_updateFeedback = "package_selected";
            c.applyBundledUpdate(); CHECK(c.m_pendingAction == "bundled-update"); c.cancelConfirmation();
            CHECK(c.hasPackage() && c.m_expectedUpdateVersion == "0.1.0.18" && c.m_updateFeedback == "package_selected");
            response(registered()); c.applyBundledUpdate(); c.confirmAction(); finish(c);
            CHECK(!c.hasPackage() && c.m_expectedUpdateVersion.isEmpty() && c.m_updateFeedback != "package_selected");
            CHECK(!requestFromCommand("update").contains("package_path"));
            settingsClearPending();
        }
        {
            // The original operation A must never attach or clear because a
            // different client's job B happens to be running or completed.
            QSettings settings; settings.setValue("pending_operation", OPERATION);
            settings.setValue("pending_operation_action", "enable"); settings.sync();
            MobileController c(&parent); c.initialize(); CHECK(c.m_operationAction == "enable");
            QVariantMap missing; missing.insert("schema", 2); missing.insert("ok", true);
            missing.insert("state", "recovery_required"); missing.insert("primary_action", "status");
            response(missing); c.refresh(); finish(c);
            CHECK(c.m_operationId == OPERATION && c.statusMessage() == c.label("operation_unknown"));
            QVariantMap job; job.insert("id", JOB); job.insert("action", "enable"); job.insert("state", "running");
            QVariantMap r; r.insert("schema", 2); r.insert("ok", true); r.insert("state", "working");
            r.insert("job_id", JOB); r.insert("job", job); r.insert("primary_action", "poll");
            r.insert("actions", QVariantList() << "poll" << "compatibility");
            response(r); c.refresh(); finish(c);
            CHECK(requestFromCommand("inspect").value("job_id").toString() == OPERATION);
            CHECK(c.m_operationId == OPERATION && c.m_jobId.isEmpty() && !c.allowed("enable"));
            job.insert("state", "completed"); r.insert("job", job); response(r); c.refresh(); finish(c);
            CHECK(c.m_operationId == OPERATION && c.m_jobId.isEmpty() && !c.allowed("enable"));
            job.insert("id", OPERATION); r.insert("job_id", OPERATION); r.insert("job", job); r.insert("live_status", true);
            response(r); c.refresh(); finish(c);
            CHECK(c.m_operationId.isEmpty() && c.m_jobId.isEmpty());
            CHECK(!QSettings().contains("pending_operation"));
            settings.setValue("pending_operation", OPERATION); settings.setValue("pending_operation_action", "enable"); settings.sync();
        }
        {
            // v13 persisted the older "export" spelling for a backup job.
            settingsClearPending(); QSettings settings;
            settings.setValue("pending_operation", OPERATION); settings.setValue("pending_operation_action", "export"); settings.sync();
            MobileController c(&parent); c.initialize(); CHECK(c.m_operationAction == "export");
            QVariantMap job; job.insert("id", OPERATION); job.insert("action", "export"); job.insert("state", "completed");
            QVariantMap r; r.insert("schema", 2); r.insert("ok", true); r.insert("state", "exported");
            r.insert("job_id", OPERATION); r.insert("job", job); r.insert("live_status", true);
            response(r); c.refresh(); finish(c);
            CHECK(requestFromCommand("inspect").value("job_id").toString() == OPERATION);
            CHECK(c.m_operationId.isEmpty() && c.m_jobId.isEmpty());
        }
        {
            // An existing job found after app reinstall is resumed with that
            // job's own identity, not a new operation ID.
            settingsClearPending(); QSettings settings; settings.setValue("pending_job", JOB); settings.sync();
            MobileController c(&parent); c.initialize();
            QVariantMap job; job.insert("id", JOB); job.insert("action", "enable"); job.insert("state", "waiting_reboot");
            QVariantMap r; r.insert("schema", 2); r.insert("ok", true); r.insert("state", "reboot_required");
            r.insert("job_id", JOB); r.insert("job", job); r.insert("primary_action", "resume");
            r.insert("actions", QVariantList() << "resume" << "compatibility");
            QVariantMap malformed = r; QVariantMap malformedJob = job;
            malformedJob.remove("id"); malformedJob.insert("state", "completed"); malformed.insert("job", malformedJob);
            response(malformed); c.refresh(); finish(c);
            CHECK(c.m_jobId == JOB && c.m_operationId.isEmpty());
            malformedJob.insert("id", OPERATION); malformed.insert("job", malformedJob);
            response(malformed); c.refresh(); finish(c);
            CHECK(c.m_jobId == JOB && c.m_operationId.isEmpty());
            QVariantMap wrong = r; QVariantMap wrongJob = job;
            wrongJob.insert("id", OPERATION); wrong.insert("job", wrongJob); wrong.insert("job_id", OPERATION);
            response(wrong); c.refresh(); finish(c);
            CHECK(c.m_jobId == JOB && c.m_operationId.isEmpty() && !c.allowed("enable"));
            response(r); c.refresh(); finish(c); CHECK(c.allowed("resume"));
            job.insert("state", "completed"); r.insert("job", job); r.insert("state", "waiting");
            r.insert("primary_action", "status"); response(r); c.requestAction("resume");
            CHECK(c.m_pendingAction == "resume"); c.confirmAction(); finish(c);
            CHECK(requestFromCommand("resume").value("operation_id").toString() == JOB);
            CHECK(c.m_operationId.isEmpty() && c.m_jobId.isEmpty());
            settingsClearPending(); settings.setValue("pending_operation", OPERATION);
            settings.setValue("pending_operation_action", "enable"); settings.sync();
        }
        {
            // Reading an apparently healthy status does not erase or replace
            // an unrelated operation whose original result is still unknown.
            MobileController c(&parent); c.initialize(); response(registered());
            c.refresh(); finish(c); CHECK(c.m_operationId == OPERATION);
            CHECK(c.primaryAction() == "inspect" && !c.allowed("confirm-calls"));
            CHECK(QSettings().value("pending_operation").toString() == OPERATION);
        }
        {
            // A diagnostic timeout must preserve the older pending identity.
            MobileController c(&parent); c.initialize(); write(ROOT + "/hang", "1");
            c.requestAction("compatibility"); spin(200); CHECK(c.busy());
            c.processTimeout(); finish(c); QFile::remove(ROOT + "/hang");
            CHECK(c.m_operationId == OPERATION && QSettings().value("pending_operation").toString() == OPERATION);
            CHECK(c.m_error == "report_unknown");
        }
        {
            // A report is not mislabeled as confirmation reconciliation.
            QSettings settings; settings.setValue("pending_operation_action", "confirm-calls");
            settings.setValue("pending_call_context", CONTEXT); settings.sync();
            MobileController c(&parent); c.initialize(); CHECK(c.m_reconcilingCalls);
            write(ROOT + "/hang", "1"); c.requestAction("compatibility"); spin(100);
            CHECK(c.busy() && !c.callConfirmationInProgress());
            c.processTimeout(); finish(c); QFile::remove(ROOT + "/hang");
            CHECK(c.m_operationId == OPERATION && c.m_pendingCallContext == CONTEXT);
        }
        {
            // An explicit current observation settles only the old call
            // confirmation and lets the user deliberately check all boxes again.
            MobileController c(&parent); c.initialize(); CHECK(c.m_reconcilingCalls);
            response(registered()); c.refresh(); finish(c);
            CHECK(c.m_operationId.isEmpty() && !QSettings().contains("pending_operation"));
            CHECK(c.allowed("confirm-calls") && c.model().value("call_context").toString() == CONTEXT);
            CHECK(c.m_notice == "calls_not_saved_notice");
        }
        {
            // If the current context changed, the old confirmation is not
            // reused; the next screen gets the new context and unchecked boxes.
            QSettings settings; settings.setValue("pending_operation", OPERATION);
            settings.setValue("pending_operation_action", "confirm-calls");
            settings.setValue("pending_call_context", CONTEXT); settings.sync();
            MobileController c(&parent); c.initialize();
            QVariantMap r = registered(); const QString newContext(32, 'd'); r.insert("call_context", newContext);
            response(r); c.refresh(); finish(c);
            CHECK(c.m_operationId.isEmpty() && c.allowed("confirm-calls"));
            CHECK(c.model().value("call_context").toString() == newContext);
            CHECK(c.m_notice == "calls_context_changed_notice");
            const int before = calls(); c.confirmCalls(true, true, true, true, CONTEXT);
            CHECK(calls() == before && c.m_error == "calls_context_changed");
            response(registered()); c.refresh(); finish(c);
            CHECK(c.model().value("call_context").toString() == CONTEXT);
        }
        settingsClearPending();
        {
            MobileController c(&parent); c.initialize(); CHECK(c.m_cachedStatus);
            write(ROOT + "/hang", "1"); c.refresh();
            CHECK(c.m_deadline.interval() == 150000); spin(200); CHECK(c.busy());
            c.processTimeout(); finish(c); QFile::remove(ROOT + "/hang");
            CHECK(c.m_cachedStatus && c.model().value("state").toString() == "registered");
            CHECK(c.m_notice == "request_timeout" && c.allowed("confirm-calls"));
            CHECK(!c.m_pollTimer.isActive());
        }
        {
            MobileController c(&parent); c.initialize(); CHECK(c.allowed("confirm-calls"));
            QVariantMap r = registered(); r.insert("state", "verified"); r.insert("primary_action", "status");
            r.insert("actions", QVariantList() << "status" << "compatibility"); response(r);
            c.confirmCalls(true, true, true, true, CONTEXT); finish(c);
            CHECK(c.model().value("state").toString() == "verified");
            const QVariantMap sent = requestFromCommand("confirm-calls");
            CHECK(sent.value("call_context").toString() == CONTEXT && sent.value("confirmed").toBool());
            CHECK(sent.value("incoming").toBool() && sent.value("outgoing").toBool() && sent.value("audio").toBool() && sent.value("lte").toBool());
            CHECK(c.m_operationId.isEmpty() && c.m_notice == "calls_saved_notice");
            CHECK(!c.allowed("confirm-calls"));
            const int before = calls(); c.confirmCalls(true, true, true, true, CONTEXT);
            CHECK(calls() == before);
        }
        {
            // An ambiguous confirmation can only lead to one observation,
            // even if the app is backgrounded, an update notice is available,
            // or the returned structure contains contradictory task fields.
            for (int i = 0; i < 8; ++i) {
                settingsClearPending(); QSettings().remove("last_observation_v1");
                MobileController c(&parent); c.m_cachedStatus = false; c.m_model = registered();
                c.m_latest.insert("version", "0.1.0.18");
                QVariantMap bad = registered(); bad.insert("state", "verified");
                if (i == 0) bad.insert("call_context", QString(32, 'd'));
                if (i == 1) bad.insert("call_context", "");
                if (i == 2) bad.insert("state", "registered");
                if (i == 3) bad.insert("schema", 1);
                if (i == 4) { bad.insert("ok", false); bad.insert("error", QVariantMap()); }
                if (i == 5) bad.insert("job_id", OPERATION);
                if (i == 6) {
                    bad.insert("ok", false); bad.insert("state", "error");
                    QVariantMap error; error.insert("code", "call_context_changed"); bad.insert("error", error);
                    bad.insert("job_id", OPERATION);
                }
                if (i == 7) {
                    bad.insert("ok", false); bad.insert("state", "error");
                    QVariantMap error; error.insert("code", "local_operation_failed"); bad.insert("error", error);
                }
                response(bad); const int before = calls();
                c.confirmCalls(true, true, true, true, CONTEXT); c.enteredBackground(); finish(c);
                CHECK(calls() == before + 1 && c.m_reconcilingCalls && c.m_refreshPending);
                CHECK(c.model().value("state").toString() == "registered" && !c.m_operationId.isEmpty());
                CHECK(!c.allowed("confirm-calls") && c.m_notice != "calls_saved_notice");
                QVariantMap observation = registered();
                if (i % 3 == 0) observation.insert("state", "verified");
                if (i % 3 == 2) observation.insert("call_context", QString(32, 'd'));
                response(observation); c.enteredForeground(); spin(500); finish(c);
                CHECK(calls() == before + 2 && c.m_operationId.isEmpty());
                CHECK(c.m_notice == (i % 3 == 0 ? "calls_saved_notice" :
                                     i % 3 == 1 ? "calls_not_saved_notice" : "calls_context_changed_notice"));
                c.screenAsleep(); c.screenAwake();
                CHECK(c.m_cachedStatus);
                CHECK(i % 3 == 0 ? c.m_notice != "calls_saved_notice" :
                      c.m_notice == (i % 3 == 1 ? "calls_not_saved_notice" : "calls_context_changed_notice"));
                spin(300); CHECK(calls() == before + 2);
            }
            settingsClearPending();
        }
        {
            // Failure of the single observation keeps the original pending
            // identity visible and never repeats the save or the observation.
            QSettings().remove("last_observation_v1");
            MobileController c(&parent); c.m_cachedStatus = false; c.m_model = registered();
            QVariantMap bad = registered(); bad.insert("call_context", ""); bad.insert("state", "verified");
            response(bad); const int before = calls();
            c.confirmCalls(true, true, true, true, CONTEXT); c.enteredBackground(); finish(c);
            QVariantMap failed; failed.insert("schema", 2); failed.insert("ok", false); failed.insert("state", "error");
            QVariantMap error; error.insert("code", "root_not_ready"); failed.insert("error", error);
            response(failed); c.enteredForeground(); spin(500); finish(c); spin(500);
            CHECK(calls() == before + 2 && !c.m_operationId.isEmpty());
            CHECK(!c.m_pollTimer.isActive() && !c.allowed("confirm-calls"));
            settingsClearPending();
        }
        {
            // Explicit pre-save rejection is not an unknown commit.
            MobileController c(&parent); c.m_cachedStatus = false; c.m_model = registered();
            QVariantMap error; error.insert("code", "call_context_changed");
            QVariantMap r; r.insert("schema", 2); r.insert("ok", false); r.insert("state", "error"); r.insert("error", error);
            response(r); c.confirmCalls(true, true, true, true, CONTEXT); finish(c);
            CHECK(c.m_operationId.isEmpty() && !QSettings().contains("pending_operation"));
            CHECK(c.statusMessage() == c.label("call_context_changed"));
            CHECK(!QSettings().contains("last_observation_v1"));
        }
        {
            // These entry errors occur before any dispatch and do not leave an
            // unresolvable confirmation identity or trigger a second request.
            for (int i = 0; i < 2; ++i) {
                settingsClearPending(); MobileController c(&parent); c.m_cachedStatus = false; c.m_model = registered();
                QVariantMap error; error.insert("code", i == 0 ? "bridge_bundle_changed" : "unsafe_bridge_entry");
                QVariantMap r; r.insert("schema", 2); r.insert("ok", false); r.insert("state", "error"); r.insert("error", error);
                response(r); const int before = calls(); c.confirmCalls(true, true, true, true, CONTEXT); finish(c); spin(250);
                CHECK(calls() == before + 1 && c.m_operationId.isEmpty());
                CHECK(!QSettings().contains("pending_operation") && !c.m_reconcilingCalls);
            }
        }
        {
            MobileController c(&parent); c.initialize(); CHECK(!c.m_cachedStatus);
            CHECK(c.model().value("state").toString() == "not_checked");
            CHECK(!c.allowed("confirm-calls") && c.primaryAction() == "inspect");
        }
        {
            // Definite pre-launch errors may clear only the newly created ID.
            MobileController c(&parent); c.m_cachedStatus = false;
            c.m_model.insert("state", "disabled"); c.m_model.insert("actions", QVariantList() << "disable");
            const int before = calls(); QVariantMap extra; extra.insert("large", QString(20000, 'x'));
            c.invoke("disable", extra);
            CHECK(calls() == before && c.m_error == "invalid_response" && c.m_operationId.isEmpty());
            CHECK(!QSettings().contains("pending_operation"));
            QSettings settings; settings.setValue("pending_operation", OPERATION);
            settings.setValue("pending_operation_action", "disable"); settings.sync();
            c.m_operationId = OPERATION; c.m_newPendingForRequest = true; c.m_action = "disable"; c.m_busy = true;
            c.processError(QProcess::FailedToStart);
            CHECK(c.m_operationId.isEmpty() && !QSettings().contains("pending_operation"));
            CHECK(calls() == before);
        }
        {
            // Exercise the real asynchronous QProcess::FailedToStart signal.
            // The nonexistent working directory prevents the fake Root from
            // ever executing, so only this newly-created operation is cleared.
            settingsClearPending();
            MobileController c(&parent); c.m_cachedStatus = false;
            c.m_model.insert("state", "disabled"); c.m_model.insert("actions", QVariantList() << "disable");
            c.m_process.setWorkingDirectory(ROOT + "/does-not-exist");
            const int before = calls(); c.invoke("disable"); finish(c);
            CHECK(calls() == before && c.m_operationId.isEmpty());
            CHECK(!QSettings().contains("pending_operation"));
        }
        {
            // The same actual startup failure during a separate report must
            // never discard an older write whose result is unknown.
            QSettings settings; settings.setValue("pending_operation", OPERATION);
            settings.setValue("pending_operation_action", "disable"); settings.sync();
            MobileController c(&parent); c.initialize();
            c.m_process.setWorkingDirectory(ROOT + "/does-not-exist");
            const int before = calls(); c.requestAction("compatibility"); finish(c);
            CHECK(calls() == before && c.m_operationId == OPERATION);
            CHECK(QSettings().value("pending_operation").toString() == OPERATION);
            settingsClearPending();
        }
        {
            // Waiting after a manually requested check remains a single read.
            QSettings settings; settings.remove("last_observation_v1"); settings.sync();
            MobileController c(&parent); c.initialize();
            QVariantMap r = registered(); r.insert("state", "waiting_sim"); r.insert("primary_action", "status");
            r.insert("actions", QVariantList() << "status" << "compatibility"); r.remove("call_context"); response(r);
            const int before = calls(); c.refresh(); finish(c); CHECK(calls() == before + 1);
            CHECK(!c.m_pollTimer.isActive()); spin(300); CHECK(calls() == before + 1);
        }
        {
            // Only a matching durable task receives one foreground check;
            // backgrounding preserves the intent without polling repeatedly.
            for (int mode = 0; mode < 3; ++mode) {
                settingsClearPending(); QSettings settings;
                settings.setValue("pending_job", OPERATION);
                if (mode != 0) settings.setValue("pending_operation", OPERATION);
                settings.setValue("pending_operation_action", "enable"); settings.sync();
                QVariantMap job; job.insert("id", OPERATION); job.insert("action", "enable");
                job.insert("state", mode == 2 ? "running" : "waiting_reboot");
                QVariantMap r; r.insert("schema", 2); r.insert("ok", true);
                r.insert("state", mode == 2 ? "working" : "reboot_required");
                r.insert("job_id", OPERATION); r.insert("job", job); r.insert("primary_action", "poll");
                r.insert("actions", QVariantList() << "poll" << "compatibility"); response(r);
                const int before = calls();
                MobileController c(&parent); c.initialize(); c.enteredBackground();
                spin(350); CHECK(calls() == before);
                c.enteredForeground(); spin(400); finish(c); spin(2000);
                CHECK(calls() == before + 1 && !c.m_pollTimer.isActive());
                CHECK(requestFromCommand("poll").value("job_id").toString() == OPERATION);
                CHECK(c.m_jobId == OPERATION && !c.allowed("enable"));
                if (mode == 2) {
                    CHECK(c.jobRunning() && !c.operationInProgress() && c.allowed("poll"));
                    c.setLanguage("zh"); CHECK(c.statusTitle() == c.label("job_last_running"));
                    CHECK(c.statusMessage() == c.label("job_last_running_help") && c.jobText().isEmpty());
                    c.setLanguage("en"); CHECK(c.statusTitle() == "Task was still running at the last check");
                }
            }
            settingsClearPending();
        }
        {
            // A diagnostic before the scheduled cold check retains that
            // check, and its success notice remains visible afterward.
            settingsClearPending(); QSettings settings;
            settings.setValue("pending_job", OPERATION); settings.setValue("pending_operation", OPERATION);
            settings.setValue("pending_operation_action", "enable"); settings.sync();
            write(ROOT + "/report-wait", "1"); QFile::remove(ROOT + "/report-ready");
            const int before = calls(); MobileController c(&parent); c.initialize();
            c.requestAction("compatibility");
            QElapsedTimer wait; wait.start(); while (calls() == before && wait.elapsed() < 5000) spin(20);
            CHECK(calls() == before + 1);
            const QString report = requestFromCommand("compatibility").value("operation_id").toString();
            QVariantMap details; details.insert("path", "/accounts/1000/shared/documents/BB10-VoLTE/" + report);
            QVariantMap saved; saved.insert("schema", 2); saved.insert("ok", true); saved.insert("state", "exported");
            saved.insert("details", details); response(saved);
            QFile::remove(ROOT + "/report-wait"); write(ROOT + "/report-ready", "1"); finish(c);
            QVariantMap job; job.insert("id", OPERATION); job.insert("action", "enable"); job.insert("state", "waiting_reboot");
            QVariantMap pending; pending.insert("schema", 2); pending.insert("ok", true); pending.insert("state", "reboot_required");
            pending.insert("job_id", OPERATION); pending.insert("job", job); pending.insert("primary_action", "poll");
            pending.insert("actions", QVariantList() << "poll" << "compatibility"); response(pending);
            spin(400); finish(c); spin(300); QFile::remove(ROOT + "/report-ready");
            CHECK(calls() == before + 2 && c.m_jobId == OPERATION);
            CHECK(c.m_notice == "report_exported" && c.exportPath() == details.value("path").toString());
            settingsClearPending();
        }
        {
            // An explicit check wins the race with the delayed cold check.
            settingsClearPending(); QSettings settings;
            settings.setValue("pending_job", OPERATION); settings.setValue("pending_operation", OPERATION);
            settings.setValue("pending_operation_action", "enable"); settings.sync();
            QVariantMap job; job.insert("id", OPERATION); job.insert("action", "enable"); job.insert("state", "waiting_reboot");
            QVariantMap r; r.insert("schema", 2); r.insert("ok", true); r.insert("state", "reboot_required");
            r.insert("job_id", OPERATION); r.insert("job", job); r.insert("primary_action", "poll");
            r.insert("actions", QVariantList() << "poll" << "compatibility"); response(r);
            const int before = calls(); MobileController c(&parent); c.initialize(); c.primary(); finish(c); spin(500);
            CHECK(calls() == before + 1 && !c.m_pollTimer.isActive());
            settingsClearPending();
        }
        {
            // A changed raw identity before the timer fires is not polled.
            settingsClearPending(); QSettings settings;
            settings.setValue("pending_job", OPERATION); settings.setValue("pending_operation", OPERATION); settings.sync();
            const int before = calls(); MobileController c(&parent); c.initialize();
            settings.setValue("pending_job", JOB); settings.sync(); spin(400);
            CHECK(calls() == before && c.m_invalidPendingIdentity);
            CHECK(QSettings().value("pending_job").toString() == JOB);
            settingsClearPending();
        }
        {
            // A completed original task without a live observation cannot
            // masquerade as an observed network state or enable a new write.
            settingsClearPending(); QSettings settings;
            settings.setValue("pending_job", OPERATION); settings.setValue("pending_operation", OPERATION);
            settings.setValue("pending_operation_action", "enable");
            settings.setValue("last_observation_v1", QVariantMap()); settings.sync();
            QVariantMap job; job.insert("id", OPERATION); job.insert("action", "enable"); job.insert("state", "completed");
            QVariantMap r; r.insert("schema", 2); r.insert("ok", true); r.insert("state", "waiting");
            r.insert("job_id", OPERATION); r.insert("job", job); r.insert("primary_action", "status");
            r.insert("actions", QVariantList() << "status" << "export" << "compatibility"); response(r);
            const int before = calls(); MobileController c(&parent); c.initialize(); spin(400); finish(c); spin(2000);
            CHECK(calls() == before + 1 && !c.m_pollTimer.isActive());
            CHECK(c.model().value("state").toString() == "task_complete_status_unchecked");
            CHECK(c.primaryAction() == "inspect" && !c.canExportBackup() && !c.allowed("enable"));
            CHECK(c.cachedStatusText().isEmpty() && !QSettings().contains("last_observation_v1"));
            job.insert("id", JOB); job.insert("state", "waiting_reboot");
            r.insert("job_id", JOB); r.insert("job", job); r.insert("state", "reboot_required");
            r.insert("primary_action", "poll"); r.insert("actions", QVariantList() << "poll" << "compatibility");
            response(r); c.refresh(); finish(c);
            CHECK(c.m_jobId == JOB && requestFromCommand("inspect").value("job_id").toString().isEmpty());
            settingsClearPending();
        }
        {
            // A structured Root error is an observation failure; never clear
            // the saved identity, retry automatically, or claim completion.
            settingsClearPending(); QSettings settings;
            settings.setValue("pending_job", OPERATION); settings.setValue("pending_operation", OPERATION);
            settings.setValue("pending_operation_action", "enable"); settings.sync();
            QVariantMap error; error.insert("code", "root_required");
            QVariantMap r; r.insert("schema", 2); r.insert("ok", false); r.insert("state", "error"); r.insert("error", error);
            response(r); const int before = calls();
            MobileController c(&parent); c.initialize(); spin(400); finish(c); spin(2000);
            CHECK(calls() == before + 1 && c.m_waitingForRoot && c.m_jobId == OPERATION);
            CHECK(QSettings().value("pending_operation").toString() == OPERATION && !c.m_pollTimer.isActive());
            settingsClearPending();
        }
        {
            // A malformed saved ID is not discarded or replaced by a cached
            // success, even after an identity-free diagnostic response.
            settingsClearPending(); QSettings settings;
            settings.setValue("pending_job", OPERATION); settings.setValue("pending_operation", "bad-id"); settings.sync();
            MobileController c(&parent); c.initialize(); const int before = calls(); spin(350);
            CHECK(calls() == before && c.m_invalidPendingIdentity && c.primaryAction() == "compatibility");
            CHECK(c.statusTitle() == c.label("pending_identity_title") && c.cachedStatusText().isEmpty());
            CHECK(!c.allowed("install") && !c.allowed("enable") && !c.allowed("confirm-calls") && !c.allowed("poll"));
            QVariantMap error; error.insert("code", "unlisted_safe_failure");
            QVariantMap r; r.insert("schema", 2); r.insert("ok", false); r.insert("state", "error"); r.insert("error", error); response(r);
            c.requestAction("compatibility"); finish(c);
            CHECK(!requestFromCommand("compatibility").contains("job_id"));
            CHECK(c.statusMessage().contains(c.label("operation_failed")));
            CHECK(QSettings().value("pending_job").toString() == OPERATION);
            CHECK(QSettings().value("pending_operation").toString() == "bad-id");
            settingsClearPending();
        }
        {
            // A changed boot/SIM is enforced by the real worker tests; here the
            // cached UI cannot inject a write when local settings are unwritable.
            QSettings::setPath(QSettings::IniFormat, QSettings::UserScope, "/proc/bb10-unwritable");
            MobileController c(&parent); c.m_cachedStatus = false;
            c.m_model.insert("state", "disabled"); c.m_model.insert("actions", QVariantList() << "disable");
            const int before = calls(); c.invoke("disable"); spin(100);
            CHECK(calls() == before && c.m_error == "state_storage_failed");
        }
        std::cout << "PASS: actual Qt controller cold start, cache, lifecycle, pending job, report isolation, timeout, call flow and settings failure" << std::endl;
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "FAIL: " << error.what() << std::endl; return 1;
    }
}
