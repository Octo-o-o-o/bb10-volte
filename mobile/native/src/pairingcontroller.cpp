#include "pairingcontroller.h"
#include "pairing_payload.h"
#include <bb/data/JsonDataAccess>
#include <QFile>
#include <QDir>
#include <QFileInfo>
#include <QRegExp>
#include <QUrl>
#include <QUuid>
#include <QVariantMap>
#include <openssl/sha.h>

PairingController::PairingController(QObject *parent) : QObject(parent),
    m_status("pair_choose_help"), m_busy(false), m_done(false), m_timedOut(false) {
    m_timer.setSingleShot(true);
    connect(&m_process, SIGNAL(started()), this, SLOT(started()));
    connect(&m_process, SIGNAL(readyReadStandardOutput()), this, SLOT(output()));
    connect(&m_process, SIGNAL(finished(int,QProcess::ExitStatus)), this, SLOT(finished(int,QProcess::ExitStatus)));
    connect(&m_process, SIGNAL(error(QProcess::ProcessError)), this, SLOT(failed(QProcess::ProcessError)));
    connect(&m_timer, SIGNAL(timeout()), this, SLOT(timeout()));
}
void PairingController::loadDownloadRequest() {
    if (m_busy) return;
    QDir downloads("/accounts/1000/shared/downloads");
    const QFileInfoList files = downloads.entryInfoList(QStringList() << "bb10-pair-*-request.json",
        QDir::Files | QDir::Readable | QDir::NoSymLinks, QDir::Name);
    QStringList matches;
    for (int i = 0; i < files.size(); ++i) {
        if (QRegExp("bb10-pair-[a-f0-9]{12}-request\\.json").exactMatch(files.at(i).fileName()))
            matches << files.at(i).absoluteFilePath();
    }
    if (matches.size() == 1) { chooseRequest(matches.first()); return; }
    m_request.clear(); m_id.clear(); m_fingerprint.clear(); m_filename.clear();
    m_resultPath.clear(); m_done = false;
    m_status = matches.isEmpty() ? "pair_download_missing" : "pair_download_multiple";
    emit changed();
}
void PairingController::chooseRequest(const QString &selected) {
    if (m_busy) return;
    m_request.clear(); m_id.clear(); m_fingerprint.clear(); m_filename.clear();
    m_resultPath.clear(); m_done = false; m_status = "pair_invalid_request";
    QString path = selected.startsWith("file:") ? QUrl(selected).toLocalFile() : selected;
    QFileInfo info(path);
    if (!info.isFile() || info.size() < 1 || info.size() > 16384) { emit changed(); return; }
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly)) { emit changed(); return; }
    QByteArray bytes = file.read(16385);
    if (bytes.isEmpty() || bytes.size() > 16384) { emit changed(); return; }
    bb::data::JsonDataAccess json;
    QVariantMap request = json.loadFromBuffer(bytes).toMap();
    if (json.hasError() || request.size() != 4 || request.value("schema").toInt() != 1 ||
        request.value("kind").toString() != "bb10-computer-pairing") { emit changed(); return; }
    QString id = request.value("request_id").toString();
    QString key = request.value("computer_public_key").toString();
    if (!QRegExp("[a-f0-9]{12}").exactMatch(id) ||
        !QRegExp("ssh-rsa [A-Za-z0-9+/]+={0,2}").exactMatch(key)) { emit changed(); return; }
    QByteArray encoded = key.mid(8).toLatin1();
    QByteArray blob = QByteArray::fromBase64(encoded);
    if (blob.size() < 128 || blob.size() > 8192 || blob.toBase64() != encoded ||
        !blob.startsWith(QByteArray("\0\0\0\7ssh-rsa", 11))) { emit changed(); return; }
    unsigned char digest[SHA256_DIGEST_LENGTH];
    SHA256(reinterpret_cast<const unsigned char *>(blob.constData()), blob.size(), digest);
    QByteArray value(reinterpret_cast<const char *>(digest), sizeof(digest));
    m_fingerprint = "SHA256:" + QString::fromLatin1(value.toBase64()).remove('=');
    // Keep exactly the previewed bytes; later shared-file changes cannot
    // substitute a different key. Root repeats strict JSON and key validation.
    m_request = bytes; m_id = id; m_filename = info.fileName();
    m_status = "pair_ready"; emit changed();
}
void PairingController::authorize() {
    if (m_busy || m_done || m_request.isEmpty()) return;
    if (!QFileInfo("/bin/__root").isExecutable()) { m_status = "pair_root_required"; emit changed(); return; }
    QByteArray payload = QByteArray::fromBase64(BB10_PAIRING_PAYLOAD_B64);
    if (payload.isEmpty()) { m_status = "pair_unavailable"; emit changed(); return; }
    QString nonce = QUuid::createUuid().toString().remove('{').remove('}').remove('-');
    QString folder = "/var/bb10_pair_bridge_" + nonce;
    QString script = folder + "/pair.py";
    m_command = QString(
        "unset PYTHONOPTIMIZE PYTHONINSPECT PYTHONSTARTUP PYTHONUSERBASE PYTHONPATH PYTHONHOME LD_PRELOAD ENV BASH_ENV\n"
        "export PATH=/proc/boot:/bin:/usr/bin:/base/bin:/base/usr/bin\n"
        "export LD_LIBRARY_PATH=/base/usr/lib:/base/lib:/base/lib/dll:/radio/lib:/radio/lib/dll:/radio/usr/lib:/proc/boot\n"
        "export PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONHOME=/usr PYTHONPATH=/usr/lib/python32.zip:/usr/lib/python3.2/lib-dynload\n"
        "umask 077\nmkdir -m 700 " + folder + " || exit 73\n"
        "trap '/usr/bin/python3.2 -B " + script + " --cleanup' 0\n"
        "cat > " + script + " <<'BB10_COMPILED_PAIRING_HELPER'\n").toUtf8();
    m_command += payload;
    m_command += QString("\nBB10_COMPILED_PAIRING_HELPER\n"
        "if [ $? -ne 0 ]; then exit 74; fi\n"
        "/proc/boot/pathtrust '!" + script + "' && /usr/bin/python3.2 -B " + script +
        " --mobile-request " + QString::fromLatin1(m_request.toBase64()) + "\nexit $?\n").toUtf8();
    m_output.clear(); m_timedOut = false; m_busy = true; m_status = "pair_working";
    QStringList environment;
    environment << "PATH=/proc/boot:/bin:/usr/bin:/base/bin:/base/usr/bin"
        << "LD_LIBRARY_PATH=/base/usr/lib:/base/lib:/base/lib/dll:/radio/lib:/radio/lib/dll:/radio/usr/lib:/proc/boot"
        << "LANG=C" << "TERM=dumb";
    m_process.setEnvironment(environment); m_process.setProcessChannelMode(QProcess::MergedChannels);
    m_timer.start(45000);
    m_process.start("/bin/__root", QStringList(), QIODevice::ReadWrite);
    emit changed();
}
void PairingController::started() { m_process.write(m_command); m_process.closeWriteChannel(); m_command.clear(); }
void PairingController::output() {
    m_output += m_process.readAllStandardOutput();
    if (m_output.size() > 65536) { m_timedOut = true; m_process.kill(); }
}
void PairingController::finished(int code, QProcess::ExitStatus status) {
    output(); m_timer.stop(); m_busy = false; m_status = "pair_unconfirmed";
    if (!m_timedOut && code == 0 && status == QProcess::NormalExit) {
        const QList<QByteArray> lines = m_output.split('\n');
        for (int i = 0; i < lines.size(); ++i) {
            bb::data::JsonDataAccess json;
            QVariantMap result = json.loadFromBuffer(lines.at(i).trimmed()).toMap();
            QString expected = "/accounts/1000/shared/downloads/bb10-pair-" + m_id + "-result.json";
            if (!json.hasError() && result.value("schema").toInt() == 1 &&
                result.value("state").toString() == "paired" && result.value("request_id").toString() == m_id &&
                result.value("fingerprint").toString() == m_fingerprint && result.value("result_path").toString() == expected) {
                m_done = true; m_resultPath = expected;
                m_status = result.value("usb_ssh_available").toBool() ? "pair_done" : "pair_done_service_pending";
            }
        }
    }
    m_output.clear(); emit changed();
}
void PairingController::failed(QProcess::ProcessError error) {
    if (error != QProcess::FailedToStart) return;
    m_timer.stop(); m_busy = false; m_command.clear(); m_status = "pair_root_required"; emit changed();
}
void PairingController::timeout() { m_timedOut = true; m_process.kill(); }
