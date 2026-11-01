import bb.cascades 1.4

Page {
    id: page
    property string callContext: ui.model.call_context || ""
    property bool initialized: false
    onCreationCompleted: initialized = true
    onCallContextChanged: {
        if (initialized) { outgoing.checked = false; incoming.checked = false; audio.checked = false; lte.checked = false; }
    }
    function t(key) { var language = ui.language; return ui.label(key); }
    titleBar: TitleBar { title: page.t("calls_title") }
    ScrollView {
        scrollViewProperties.scrollMode: ScrollMode.Vertical
        Container {
            leftPadding: 24
            rightPadding: 24
            topPadding: 20
            bottomPadding: 32
            Label { text: page.t("calls_note"); multiline: true; textFormat: TextFormat.Plain }
            CheckBox { id: outgoing; text: page.t("calls_outgoing") }
            CheckBox { id: incoming; text: page.t("calls_incoming") }
            CheckBox { id: audio; text: page.t("calls_audio") }
            CheckBox { id: lte; text: page.t("calls_lte") }
            Button {
                text: page.t("confirm-calls")
                horizontalAlignment: HorizontalAlignment.Fill
                enabled: page.callContext.length === 32 && outgoing.checked && incoming.checked && audio.checked && lte.checked && !ui.busy && ui.allowed("confirm-calls")
                onClicked: ui.confirmCalls(outgoing.checked, incoming.checked, audio.checked, lte.checked, page.callContext)
            }
            Label { text: ui.statusTitle; multiline: true; textFormat: TextFormat.Plain }
            Label { text: ui.statusMessage; multiline: true; textFormat: TextFormat.Plain }
            Label { text: ui.jobText; visible: text.length > 0; multiline: true; textFormat: TextFormat.Plain }
        }
    }
}
