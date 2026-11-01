#ifndef BB10_MOBILE_CONTROLLER_H
#define BB10_MOBILE_CONTROLLER_H

#include <QObject>
#include <QVariantMap>
#include <QProcess>
#include <QTimer>
#include <QSettings>
#include <QtNetwork/QNetworkAccessManager>
#include <QtNetwork/QNetworkReply>
#include <QFile>
#include <openssl/sha.h>

class MobileController : public QObject {
    Q_OBJECT
    Q_PROPERTY(QVariantMap model READ model NOTIFY modelChanged)
    Q_PROPERTY(QString language READ language WRITE setLanguage NOTIFY languageChanged)
    Q_PROPERTY(QString statusTitle READ statusTitle NOTIFY modelChanged)
    Q_PROPERTY(QString statusMessage READ statusMessage NOTIFY modelChanged)
    Q_PROPERTY(QString primaryText READ primaryText NOTIFY modelChanged)
    Q_PROPERTY(QString primaryAction READ primaryAction NOTIFY modelChanged)
    Q_PROPERTY(QString detailText READ detailText NOTIFY modelChanged)
    Q_PROPERTY(QString deviceText READ deviceText NOTIFY modelChanged)
    Q_PROPERTY(QString carrierText READ carrierText NOTIFY modelChanged)
    Q_PROPERTY(QString jobText READ jobText NOTIFY modelChanged)
    Q_PROPERTY(QString notice READ notice NOTIFY modelChanged)
    Q_PROPERTY(QString exportPath READ exportPath NOTIFY modelChanged)
    Q_PROPERTY(QString backupLocation READ backupLocation WRITE setBackupLocation NOTIFY settingsChanged)
    Q_PROPERTY(QString legacyProfile READ legacyProfile WRITE setLegacyProfile NOTIFY settingsChanged)
    Q_PROPERTY(QString packageName READ packageName NOTIFY settingsChanged)
    Q_PROPERTY(QString version READ version CONSTANT)
    Q_PROPERTY(QString confirmationTitle READ confirmationTitle NOTIFY confirmationNeeded)
    Q_PROPERTY(QString confirmationBody READ confirmationBody NOTIFY confirmationNeeded)
    Q_PROPERTY(bool busy READ busy NOTIFY modelChanged)
    Q_PROPERTY(bool jobRunning READ jobRunning NOTIFY modelChanged)
    Q_PROPERTY(bool sdAvailable READ sdAvailable NOTIFY settingsChanged)
    Q_PROPERTY(bool hasPackage READ hasPackage NOTIFY settingsChanged)
    Q_PROPERTY(bool hasUpdate READ hasUpdate NOTIFY modelChanged)
    Q_PROPERTY(bool canApplyBundledUpdate READ canApplyBundledUpdate NOTIFY modelChanged)

public:
    explicit MobileController(QObject *parent = 0);
    void initialize();
    QVariantMap model() const { return m_model; }
    QString language() const { return m_language; }
    void setLanguage(const QString &value);
    QString statusTitle() const;
    QString statusMessage() const;
    QString primaryText() const;
    QString primaryAction() const;
    QString detailText() const;
    QString deviceText() const;
    QString carrierText() const;
    QString jobText() const;
    QString notice() const;
    QString exportPath() const { return m_lastExportPath; }
    QString version() const;
    QString backupLocation() const { return m_backupLocation; }
    void setBackupLocation(const QString &value);
    QString legacyProfile() const { return m_legacyProfile; }
    void setLegacyProfile(const QString &value);
    QString packageName() const;
    QString confirmationTitle() const;
    QString confirmationBody() const;
    bool busy() const { return m_busy; }
    bool jobRunning() const;
    bool sdAvailable() const;
    bool hasPackage() const { return !m_packagePath.isEmpty(); }
    bool hasUpdate() const { return !m_update.isEmpty(); }
    bool canApplyBundledUpdate() const { return m_model.value("details").toMap().value("bundled_update_available").toBool(); }

    Q_INVOKABLE QString label(const QString &key) const;
    Q_INVOKABLE bool allowed(const QString &action) const;
    Q_INVOKABLE void refresh();
    Q_INVOKABLE void primary();
    Q_INVOKABLE void requestAction(const QString &action);
    Q_INVOKABLE void applyBundledUpdate();
    Q_INVOKABLE void confirmAction();
    Q_INVOKABLE void cancelConfirmation();
    Q_INVOKABLE void choosePackage(const QString &path);
    Q_INVOKABLE void confirmCalls(bool outgoing, bool incoming, bool audio, bool lte, const QString &context);
    Q_INVOKABLE void exportBackup();
    Q_INVOKABLE void legacyAction(const QString &action, const QString &profileId);
    Q_INVOKABLE void checkUpdate();
    Q_INVOKABLE void downloadUpdate();

signals:
    void modelChanged();
    void languageChanged();
    void settingsChanged();
    void confirmationNeeded();

private slots:
    void processStarted();
    void processOutput();
    void processErrorOutput();
    void processFinished(int code, QProcess::ExitStatus status);
    void processError(QProcess::ProcessError error);
    void processTimeout();
    void poll();
    void networkReady();
    void networkFinished();
    void networkTimeout();

private:
    static bool knownAction(const QString &action);
    static bool readAction(const QString &action);
    static bool safeId(const QString &value);
    static bool knownProfile(const QString &value);
    static QString shellQuote(const QString &value);
    static bool trustedUrl(const QUrl &url);
    bool verifyEntry(QByteArray *bytes, QString *bundlePath);
    void invoke(const QString &action, const QVariantMap &extra = QVariantMap());
    void acceptResponse(const QVariantMap &response);
    void fail(const QString &code);
    void beginNetwork(const QUrl &url);
    void finishNetworkError(const QString &code);
    void beginDownload();
    QString display(const QString &key, const QString &code) const;
    QString newOperationId() const;

    QSettings m_settings;
    QVariantMap m_model;
    QString m_language;
    QString m_backupLocation;
    QString m_legacyProfile;
    QString m_checkedLegacyProfile;
    QString m_requestedLegacyProfile;
    QString m_packagePath;
    QString m_error;
    QString m_notice;
    QString m_lastExportPath;
    QString m_jobId;
    QString m_operationId;
    QString m_action;
    QByteArray m_command;
    QString m_pendingAction;
    QVariantMap m_pendingExtra;
    QProcess m_process;
    QTimer m_deadline;
    QTimer m_pollTimer;
    QByteArray m_output;
    bool m_busy;
    bool m_timedOut;
    bool m_runtimeError;
    bool m_refreshLegacy;
    QNetworkAccessManager m_network;
    QNetworkReply *m_reply;
    QTimer m_networkDeadline;
    QString m_transfer;
    QByteArray m_metadata;
    QVariantMap m_update;
    QFile m_download;
    SHA256_CTX m_downloadHash;
    qint64 m_downloadBytes;
    int m_redirects;
};
#endif
