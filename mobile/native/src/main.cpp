#include <bb/cascades/AbstractPane>
#include <bb/cascades/Application>
#include <bb/cascades/QmlDocument>
#include <QDeclarativeContext>
#include "mobilecontroller.h"
#include "supportcontroller.h"
#include "pairingcontroller.h"

Q_DECL_EXPORT int main(int argc, char **argv)
{
    bb::cascades::Application app(argc, argv);
    QCoreApplication::setOrganizationName("OctoLab");
    QCoreApplication::setApplicationName("BB10VoLTE");
    MobileController controller(&app);
    SupportController support(&app);
    PairingController pairing(&app);
    bb::cascades::QmlDocument *document = bb::cascades::QmlDocument::create("asset:///main.qml").parent(&app);
    if (document->hasErrors()) return 1;
    document->documentContext()->setContextProperty("volteController", &controller);
    document->documentContext()->setContextProperty("supportController", &support);
    document->documentContext()->setContextProperty("pairingController", &pairing);
    bb::cascades::AbstractPane *scene = document->createRootObject<bb::cascades::AbstractPane>();
    if (!scene) return 1;
    app.setScene(scene);
    controller.initialize();
    return bb::cascades::Application::exec();
}
