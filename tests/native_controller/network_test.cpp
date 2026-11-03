// Tests actual controller update handling with a fake, offline Qt reply.
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
#include <QJsonDocument>
#include <QThread>
#include <cstring>
#include <iostream>
#include <stdexcept>

#define CHECK(value) do { if (!(value)) throw std::runtime_error(std::string(__func__) + ":" + std::to_string(__LINE__) + ": " + #value); } while (0)

class FakeReply : public QNetworkReply {
public:
    explicit FakeReply(QObject *parent, const QByteArray &data = QByteArray())
        : QNetworkReply(parent), m_data(data), m_offset(0)
    {
        setUrl(QUrl("https://bb10-downloads.octoooo.com/mobile/test"));
        setAttribute(QNetworkRequest::HttpStatusCodeAttribute, 200);
        open(QIODevice::ReadOnly);
        setFinished(true);
    }
    void abort() override {}
    qint64 bytesAvailable() const override { return m_data.size() - m_offset + QIODevice::bytesAvailable(); }
    qint64 readData(char *target, qint64 limit) override {
        const qint64 amount = qMin(limit, qint64(m_data.size()) - m_offset);
        if (amount <= 0) return -1;
        std::memcpy(target, m_data.constData() + m_offset, size_t(amount));
        m_offset += amount;
        return amount;
    }
private:
    QByteArray m_data;
    qint64 m_offset;
};

static QVariantMap metadata(const QString &version, qint64 size = 100)
{
    QVariantMap value;
    value.insert("schema", 2); value.insert("size", size); value.insert("version", version);
    value.insert("sha256", QString(64, 'a'));
    value.insert("package_url", "https://bb10-downloads.octoooo.com/mobile/update.zip");
    return value;
}

static void finishMetadata(MobileController &c, const QVariantMap &value)
{
    c.m_metadata = QJsonDocument::fromVariant(value).toJson(QJsonDocument::Compact);
    c.m_reply = new FakeReply(&c); c.m_transfer = "metadata"; c.m_busy = true;
    c.m_transferElapsed.start(); c.networkFinished();
}

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    QCoreApplication::setOrganizationName("BB10ControllerHarness");
    QCoreApplication::setApplicationName("OfflineUpdateTests");
    QSettings::setDefaultFormat(QSettings::IniFormat);
    QSettings::setPath(QSettings::IniFormat, QSettings::UserScope, "/tmp/bb10-update-test-settings");
    QSettings().clear(); QObject parent;
    try {
        const QStringList current = QString("0.1.0.17,0.1.0.16,0.1.0.18").split(',');
        const QStringList latest = QString("0.1.0.17,0.1.0.17,0.1.0.18").split(',');
        const QStringList notices = QString("up_to_date,update_available,app_update_available").split(',');
        for (int i = 0; i < current.size(); ++i) {
            MobileController c(&parent); c.m_cachedStatus = false;
            QVariantMap details; details.insert("version", current.at(i)); c.m_model.insert("details", details);
            finishMetadata(c, metadata(latest.at(i)));
            CHECK(c.m_error.isEmpty() && c.m_notice == notices.at(i));
            CHECK(!c.m_update.isEmpty() == (i == 1));
        }
        {
            MobileController c(&parent); c.m_cachedStatus = false;
            QVariantMap details; details.insert("version", "0.1.0.15"); c.m_model.insert("details", details);
            finishMetadata(c, metadata("0.1.0.18"));
            CHECK(c.m_notice == "both_updates_available" && !c.m_update.isEmpty());
            c.setExperimentalVisible(true); c.setExperimentalVisible(false);
            CHECK(c.m_cachedStatus && c.m_notice == "app_update_check_service" && c.m_update.isEmpty());
        }
        {
            // Runtime version is never labeled as an installed service
            // revision; old, missing and installed services remain distinct.
            const QStringList states = QString("legacy,absent,installed").split(',');
            for (int i = 0; i < states.size(); ++i) {
                MobileController c(&parent); c.m_cachedStatus = false; c.setLanguage("en");
                QVariantMap details; details.insert("version", "0.1.0.16"); details.insert("service_state", states.at(i));
                c.m_model.insert("details", details);
                CHECK(c.runtimeVersionText() == "0.1.0.16");
                CHECK(c.phoneServiceText() == c.label("service_" + states.at(i)));
                c.setLanguage("zh"); CHECK(c.phoneServiceText() == c.label("service_" + states.at(i)));
                finishMetadata(c, metadata("0.1.0.16"));
                CHECK(c.m_notice == "up_to_date" && c.label("up_to_date").contains(QString::fromUtf8("首页")));
            }
        }
        {
            MobileController c(&parent); c.m_cachedStatus = true;
            QVariantMap details; details.insert("version", "0.1.0.15"); c.m_model.insert("details", details);
            finishMetadata(c, metadata("0.1.0.18"));
            CHECK(c.m_notice == "app_update_check_service" && c.m_update.isEmpty());
            c.m_cachedStatus = false; c.refreshUpdateAvailability();
            CHECK(c.m_notice == "both_updates_available" && !c.m_update.isEmpty());
            details.insert("version", "0.1.0.18"); c.m_model.insert("details", details);
            c.refreshUpdateAvailability();
            CHECK(c.m_notice == "app_update_available" && c.m_update.isEmpty());
        }
        for (int i = 0; i < 2; ++i) {
            MobileController c(&parent); c.m_cachedStatus = false;
            QVariantMap details; details.insert("version", "0.1.0.15"); c.m_model.insert("details", details);
            finishMetadata(c, i == 0 ? metadata("0.1.16") : metadata("0.1.0.17", 33LL * 1024 * 1024));
            CHECK(c.m_error.isEmpty() && c.m_updateFeedback == "bad_update_metadata" && c.m_update.isEmpty());
        }
        {
            MobileController c(&parent); c.m_transfer = "package"; c.m_busy = true;
            c.m_transferElapsed.start(); c.m_downloadBytes = 0; c.m_update.insert("size", 100);
            const QString path = "/tmp/bb10-update-network-test.part";
            c.m_download.setFileName(path); CHECK(c.m_download.open(QIODevice::WriteOnly | QIODevice::Truncate));
            SHA256_Init(&c.m_downloadHash); c.m_reply = new FakeReply(&c, QByteArray("12345"));
            c.m_networkDeadline.start(10000); QThread::msleep(50); c.networkReady();
            CHECK(c.m_downloadBytes == 5 && c.m_networkDeadline.remainingTime() > 140000);
            c.m_networkDeadline.stop(); c.m_download.close(); QFile::remove(path);
        }
        {
            // Oversized server data is a package-integrity failure, while a
            // real local write failure reports storage permissions/space.
            for (int i = 0; i < 2; ++i) {
                MobileController c(&parent); c.setLanguage("zh");
                c.m_transfer = "package"; c.m_busy = true; c.m_downloadBytes = 0;
                c.m_update.insert("size", i == 0 ? 3 : 10);
                c.m_reply = new FakeReply(&c, QByteArray("12345"));
                SHA256_Init(&c.m_downloadHash); c.m_transferElapsed.start(); c.networkReady();
                CHECK(!c.busy() && c.m_updateFeedback == (i == 0 ? "package_changed" : "storage_denied"));
                CHECK(c.updateFeedback() == c.label(c.m_updateFeedback));
                const QString zh = c.updateFeedback(); c.setLanguage("en");
                CHECK(c.updateFeedback() == c.label(c.m_updateFeedback) && c.updateFeedback() != zh);
            }
        }
        {
            // A bad replacement package cannot leave the old one armed.
            MobileController c(&parent); c.m_packagePath = "/old/update.zip";
            c.m_expectedUpdateVersion = "0.1.0.18"; c.m_expectedUpdateSha256 = QString(64, 'a');
            c.m_error = "call_active"; c.m_runtimeError = true;
            c.m_notice = "calls_context_changed_notice"; c.choosePackage("/missing/not-a-package.zip");
            CHECK(!c.hasPackage() && c.m_expectedUpdateVersion.isEmpty() && c.m_expectedUpdateSha256.isEmpty());
            CHECK(c.m_error == "call_active" && c.m_notice == "calls_context_changed_notice" && c.updateFeedback() == c.label("package_invalid"));
            c.m_packagePath = "/old/update.zip"; c.packagePickerError();
            CHECK(c.hasPackage() && c.updateFeedback() == c.label("package_picker_error"));
        }
        {
            // Network cancellation is safe and idempotent; after the transfer
            // transitions to Root, the same control cannot cancel the job.
            MobileController c(&parent); c.m_transfer = "metadata"; c.m_busy = true;
            c.m_reply = new FakeReply(&c); CHECK(c.networkTransferInProgress());
            c.cancelUpdateTransfer();
            CHECK(!c.busy() && !c.m_reply && c.m_updateFeedback == "update_transfer_cancelled");
            CHECK(c.updateFeedback() == c.label("update_transfer_cancelled"));
            c.networkFinished(); c.cancelUpdateTransfer();
            CHECK(c.m_updateFeedback == "update_transfer_cancelled");
            c.m_busy = true; c.m_action = "update"; c.m_transfer.clear();
            c.cancelUpdateTransfer(); CHECK(c.busy() && c.m_action == "update");
        }
        {
            // The download can finish before Root starts; a local launch error
            // must not leave an obsolete "downloading" notice on screen.
            MobileController c(&parent); c.m_cachedStatus = false;
            c.m_model.insert("actions", QVariantList() << "update");
            const QByteArray bytes("complete-update");
            unsigned char digest[SHA256_DIGEST_LENGTH];
            SHA256(reinterpret_cast<const unsigned char *>(bytes.constData()), size_t(bytes.size()), digest);
            c.m_update = metadata("0.1.0.18", bytes.size());
            c.m_update.insert("sha256", QString::fromLatin1(QByteArray(reinterpret_cast<const char *>(digest), SHA256_DIGEST_LENGTH).toHex()));
            const QString part = "/tmp/bb10-update-complete-test.zip.part";
            QFile::remove(part); QFile::remove(part.left(part.size() - 5));
            c.m_download.setFileName(part); CHECK(c.m_download.open(QIODevice::WriteOnly | QIODevice::Truncate));
            c.m_transfer = "package"; c.m_busy = true; c.m_updateFeedback = "downloading_update"; c.m_notice = "update_available";
            c.m_downloadBytes = 0; SHA256_Init(&c.m_downloadHash); c.m_transferElapsed.start();
            c.m_reply = new FakeReply(&c, bytes); c.networkFinished();
            CHECK(!c.busy() && c.hasPackage() && c.m_updateFeedback != "downloading_update" && c.m_notice.isEmpty());
            CHECK(!c.m_error.isEmpty() && c.updateFeedback() == c.label(c.m_error));
            QFile::remove(c.m_packagePath);
        }
        {
            MobileController c(&parent); c.m_transfer = "metadata"; c.m_busy = true;
            c.m_error = "call_active"; c.m_runtimeError = true;
            c.networkTimeout(); CHECK(c.m_error == "call_active" && c.m_updateFeedback == "update_check_timeout" && !c.busy());
            c.m_transfer = "package"; c.m_busy = true;
            c.networkTimeout(); CHECK(c.m_error == "call_active" && c.m_updateFeedback == "download_timeout" && !c.busy());
        }
        {
            // A network check and cancellation do not erase a phone fault.
            MobileController c(&parent); c.m_error = "call_active"; c.m_runtimeError = true;
            c.checkUpdate(); CHECK(c.busy() && c.m_error == "call_active");
            c.cancelUpdateTransfer();
            CHECK(!c.busy() && c.m_error == "call_active" && c.m_runtimeError);
            CHECK(c.updateFeedback() == c.label("update_transfer_cancelled"));
        }
        std::cout << "PASS: update versions, cache, metadata limits and progress deadlines" << std::endl;
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "FAIL: " << error.what() << std::endl; return 1;
    }
}
