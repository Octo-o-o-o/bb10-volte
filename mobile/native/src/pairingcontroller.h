#ifndef BB10_PAIRING_CONTROLLER_H
#define BB10_PAIRING_CONTROLLER_H
#include <QObject>
#include <QProcess>
#include <QTimer>
class PairingController : public QObject {
    Q_OBJECT
    Q_PROPERTY(QString requestId READ requestId NOTIFY changed)
    Q_PROPERTY(QString fingerprint READ fingerprint NOTIFY changed)
    Q_PROPERTY(QString filename READ filename NOTIFY changed)
    Q_PROPERTY(QString statusKey READ statusKey NOTIFY changed)
    Q_PROPERTY(QString resultPath READ resultPath NOTIFY changed)
    Q_PROPERTY(bool busy READ busy NOTIFY changed)
    Q_PROPERTY(bool done READ done NOTIFY changed)
    Q_PROPERTY(bool hasRequest READ hasRequest NOTIFY changed)
public:
    explicit PairingController(QObject *parent = 0);
    QString requestId() const { return m_id; }
    QString fingerprint() const { return m_fingerprint; }
    QString filename() const { return m_filename; }
    QString statusKey() const { return m_status; }
    QString resultPath() const { return m_resultPath; }
    bool busy() const { return m_busy; }
    bool done() const { return m_done; }
    bool hasRequest() const { return !m_request.isEmpty(); }
    Q_INVOKABLE void chooseRequest(const QString &path);
    Q_INVOKABLE void loadDownloadRequest();
    Q_INVOKABLE void authorize();
signals:
    void changed();
private slots:
    void started();
    void output();
    void finished(int code, QProcess::ExitStatus status);
    void failed(QProcess::ProcessError error);
    void timeout();
private:
    QByteArray m_request, m_command, m_output;
    QString m_id, m_fingerprint, m_filename, m_status, m_resultPath;
    bool m_busy, m_done, m_timedOut;
    QProcess m_process;
    QTimer m_timer;
};
#endif
