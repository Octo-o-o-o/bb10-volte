import bb.cascades 1.4

Page {
    id: page
    property string callContext: volteController.model.call_context || ""
    property bool checksEditable: volteController.model.state !== "verified" && !volteController.busy && volteController.allowed("confirm-calls")
    property bool initialized: false
    onCreationCompleted: initialized = true
    onCallContextChanged: {
        if (initialized) { outgoing.checked = false; incoming.checked = false; audio.checked = false; lte.checked = false; }
    }
    function t(key) { var language = volteController.language; return volteController.label(key); }
    titleBar: TitleBar { title: page.t("calls_title") }
    ScrollView {
        scrollViewProperties.scrollMode: ScrollMode.Vertical
        Container {
            leftPadding: 24
            rightPadding: 24
            topPadding: 20
            bottomPadding: 32
            Label { text: page.t("calls_note"); multiline: true; textFormat: TextFormat.Plain }
            Label { text: volteController.cachedStatusText; visible: text.length > 0; multiline: true; textStyle.fontSize: FontSize.Small; textFormat: TextFormat.Plain }
            Label { text: volteController.notice; visible: text.length > 0 && text !== page.t("calls_saved_notice"); multiline: true; textFormat: TextFormat.Plain }
            CheckBox { id: outgoing; text: page.t("calls_outgoing"); enabled: page.checksEditable }
            CheckBox { id: incoming; text: page.t("calls_incoming"); enabled: page.checksEditable }
            CheckBox { id: audio; text: page.t("calls_audio"); enabled: page.checksEditable }
            CheckBox { id: lte; text: page.t("calls_lte"); enabled: page.checksEditable }
            Button {
                text: page.t("confirm-calls")
                horizontalAlignment: HorizontalAlignment.Fill
                enabled: page.callContext.length === 32 && outgoing.checked && incoming.checked && audio.checked && lte.checked && !volteController.busy && volteController.allowed("confirm-calls")
                onClicked: volteController.confirmCalls(outgoing.checked, incoming.checked, audio.checked, lte.checked, page.callContext)
            }
            Label { text: volteController.notice; visible: text === page.t("calls_saved_notice"); multiline: true; textFormat: TextFormat.Plain }
            Label { text: volteController.statusTitle; multiline: true; textFormat: TextFormat.Plain }
            Label { text: volteController.statusMessage; multiline: true; textFormat: TextFormat.Plain }
            Button { text: page.t("status"); horizontalAlignment: HorizontalAlignment.Fill; enabled: !volteController.busy && !volteController.operationInProgress; onClicked: volteController.refresh() }
            Label { text: volteController.jobText; visible: text.length > 0; multiline: true; textFormat: TextFormat.Plain }
        }
    }
}
