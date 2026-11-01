import bb.cascades 1.4
import bb.system 1.2

NavigationPane {
    id: navigation
    function t(key) { var language = ui.language; return ui.label(key); }
    onPopTransitionEnded: { page.destroy(); }
    onCreationCompleted: {
        ui.confirmationNeeded.connect(function() { confirmation.show(); });
    }
    Page {
        id: home
        titleBar: TitleBar { title: "BB10 VoLTE" }
        actions: [
            ActionItem {
                title: navigation.t("advanced")
                ActionBar.placement: ActionBarPlacement.OnBar
                onTriggered: {
                    var page = managePage.createObject();
                    page.navigation = navigation;
                    navigation.push(page);
                }
            },
            ActionItem {
                title: navigation.t("status")
                enabled: !ui.busy
                shortcuts: [ Shortcut { key: "R" } ]
                onTriggered: ui.refresh()
            }
        ]
        ScrollView {
            horizontalAlignment: HorizontalAlignment.Fill
            verticalAlignment: VerticalAlignment.Fill
            scrollViewProperties.scrollMode: ScrollMode.Vertical
            Container {
                leftPadding: 24
                rightPadding: 24
                topPadding: 20
                bottomPadding: 32
                Label {
                    text: navigation.t("tagline")
                    multiline: true
                    textStyle.fontSize: FontSize.Small
                    textFormat: TextFormat.Plain
                }
                Label {
                    text: ui.deviceText + "  ·  " + ui.carrierText
                    multiline: true
                    textStyle.fontSize: FontSize.Small
                    textFormat: TextFormat.Plain
                }
                Divider {}
                Label {
                    text: ui.statusTitle
                    multiline: true
                    textStyle.fontSize: FontSize.XLarge
                    textStyle.fontWeight: FontWeight.W500
                    textFormat: TextFormat.Plain
                }
                Label {
                    text: ui.statusMessage
                    visible: text.length > 0
                    multiline: true
                    textFormat: TextFormat.Plain
                }
                ActivityIndicator {
                    visible: ui.busy || ui.jobRunning
                    running: visible
                    preferredWidth: 72
                    preferredHeight: 72
                    horizontalAlignment: HorizontalAlignment.Center
                }
                Label {
                    text: ui.jobText
                    visible: text.length > 0
                    multiline: true
                    textStyle.fontSize: FontSize.Small
                    textFormat: TextFormat.Plain
                }
                Container {
                    visible: ui.primaryAction === "install" || ui.model.state === "backup_required" || ui.model.state === "needs_backup_location"
                    DropDown {
                        title: navigation.t("backup_title")
                        enabled: !ui.busy && !ui.jobRunning
                        options: [
                            Option { text: navigation.t("backup_internal"); value: "internal"; selected: ui.backupLocation === "internal" },
                            Option { text: navigation.t("backup_sd"); value: "sdcard"; enabled: ui.sdAvailable; selected: ui.backupLocation === "sdcard" }
                        ]
                        onSelectedOptionChanged: { if (selectedOption) ui.backupLocation = selectedOption.value; }
                    }
                    Label {
                        text: navigation.t(ui.backupLocation === "sdcard" ? "backup_sd_note" : "backup_internal_note")
                        multiline: true
                        textStyle.fontSize: FontSize.Small
                        textFormat: TextFormat.Plain
                    }
                }
                Button {
                    text: ui.primaryText
                    horizontalAlignment: HorizontalAlignment.Fill
                    enabled: !ui.busy && ui.allowed(ui.primaryAction)
                    onClicked: {
                        if (ui.primaryAction === "confirm-calls") navigation.push(callPage.createObject());
                        else ui.primary();
                    }
                }
                Button {
                    text: navigation.t("confirm-calls")
                    horizontalAlignment: HorizontalAlignment.Fill
                    visible: { var state = ui.model; return ui.allowed("confirm-calls") && ui.primaryAction !== "confirm-calls"; }
                    enabled: !ui.busy && !ui.jobRunning
                    onClicked: navigation.push(callPage.createObject())
                }
                Label {
                    text: ui.notice
                    visible: text.length > 0
                    multiline: true
                    textStyle.fontSize: FontSize.Small
                    textFormat: TextFormat.Plain
                }
                Label {
                    text: navigation.t("export_path") + ": " + ui.exportPath
                    visible: ui.exportPath.length > 0
                    multiline: true
                    textStyle.fontSize: FontSize.Small
                    textFormat: TextFormat.Plain
                }
            }
        }
    }
    attachedObjects: [
        ComponentDefinition { id: managePage; source: "Manage.qml" },
        ComponentDefinition { id: callPage; source: "CallCheck.qml" },
        SystemDialog {
            id: confirmation
            title: ui.confirmationTitle
            body: ui.confirmationBody
            confirmButton.label: navigation.t("continue")
            cancelButton.label: navigation.t("cancel")
            onFinished: {
                if (result === SystemUiResult.ConfirmButtonSelection) ui.confirmAction();
                else ui.cancelConfirmation();
            }
        }
    ]
}
