#ifndef BB10_SUPPORT_CONTROLLER_H
#define BB10_SUPPORT_CONTROLLER_H

#include <QObject>
#include <QTimer>
#include <bb/system/InvokeManager>

class SupportController : public QObject {
    Q_OBJECT
    Q_PROPERTY(QString messageKey READ messageKey NOTIFY changed)
    Q_PROPERTY(QString lastLink READ lastLink NOTIFY changed)
    Q_PROPERTY(bool opening READ opening NOTIFY changed)
public:
    explicit SupportController(QObject *parent = 0);
    QString messageKey() const { return m_message; }
    QString lastLink() const { return m_link; }
    bool opening() const { return m_opening; }
    Q_INVOKABLE void openLink(const QString &id);
    Q_INVOKABLE void copyLink();
    Q_INVOKABLE void reset();
signals:
    void changed();
private slots:
    void finished();
    void timedOut();
private:
    bb::system::InvokeManager m_invoker;
    QObject *m_reply;
    QTimer m_timer;
    QString m_message;
    QString m_link;
    bool m_opening;
};
#endif
