import bb.cascades 1.4
import bb.cascades.pickers 1.0
Page {
    id: page
    function t(key) { var language = volteController.language; return volteController.label(key); }
    onCreationCompleted: {
        if (!pairingController.hasRequest && !pairingController.done && !pairingController.busy)
            pairingController.loadDownloadRequest();
    }
    titleBar: TitleBar { title: page.t("pair_title") }
    ScrollView {
        scrollViewProperties.scrollMode: ScrollMode.Vertical
        Container {
            leftPadding: 24; rightPadding: 24; topPadding: 24; bottomPadding: 32
            Label { text: page.t("pair_intro"); visible: !pairingController.done; multiline: true; textFormat: TextFormat.Plain }
            Label { text: pairingController.filename; visible: text.length > 0 && !pairingController.done; multiline: true; textStyle.fontSize: FontSize.Small; textFormat: TextFormat.Plain }
            Label { text: page.t("pair_request_id") + pairingController.requestId; visible: pairingController.hasRequest && !pairingController.done; multiline: true; textFormat: TextFormat.Plain }
            Label { text: page.t("pair_computer_fp") + pairingController.fingerprint; visible: pairingController.hasRequest && !pairingController.done; multiline: true; textStyle.fontSize: FontSize.Small; textFormat: TextFormat.Plain }
            Label { text: page.t("pair_match"); visible: pairingController.hasRequest && !pairingController.done; multiline: true; textFormat: TextFormat.Plain }
            Button {
                text: page.t("pair_authorize"); horizontalAlignment: HorizontalAlignment.Fill
                enabled: pairingController.hasRequest && !pairingController.busy && !pairingController.done
                onClicked: pairingController.authorize()
            }
            ActivityIndicator { running: pairingController.busy; visible: pairingController.busy; preferredWidth: 72; preferredHeight: 72 }
            Label {
                text: page.t("pair_host_code") + pairingController.hostShortCode
                visible: pairingController.done && pairingController.hostShortCode.length > 0
                multiline: true
                textStyle.fontSize: FontSize.Large
                textStyle.fontWeight: FontWeight.W500
                textFormat: TextFormat.Plain
            }
            Label {
                text: page.t("pair_host_fp") + pairingController.hostFingerprint
                visible: pairingController.done && pairingController.hostFingerprint.length > 0
                multiline: true
                textStyle.fontSize: FontSize.Small
                textFormat: TextFormat.Plain
            }
            Label { text: page.t(pairingController.statusKey); multiline: true; textFormat: TextFormat.Plain }
            Label {
                text: page.t("pair_result_fallback") + "\n" + pairingController.resultPath
                visible: pairingController.done && pairingController.resultPath.length > 0
                multiline: true
                textStyle.fontSize: FontSize.Small
                textFormat: TextFormat.Plain
            }
            Button {
                text: page.t(pairingController.done ? "pair_load_another" : "pair_load_downloads")
                horizontalAlignment: HorizontalAlignment.Fill
                enabled: !pairingController.busy
                onClicked: pairingController.loadDownloadRequest()
            }
            Button {
                text: page.t("pair_choose")
                horizontalAlignment: HorizontalAlignment.Fill
                enabled: !pairingController.busy
                onClicked: requestPicker.open()
            }
        }
    }
    attachedObjects: [
        FilePicker {
            id: requestPicker
            title: page.t("pair_choose")
            type: FileType.Other; mode: FilePickerMode.Picker
            filter: ["*.json"]
            directories: ["/accounts/1000/shared/downloads", "/accounts/1000/removable/sdcard"]
            onFileSelected: { if (selectedFiles.length === 1) pairingController.chooseRequest(selectedFiles[0]); }
        }
    ]
}
