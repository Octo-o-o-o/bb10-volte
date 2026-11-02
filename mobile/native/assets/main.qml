import bb.cascades 1.4
import bb.system 1.2

NavigationPane {
    id: navigation
    function t(key) { var language = volteController.language; return volteController.label(key); }
    onPopTransitionEnded: { page.destroy(); }
    onTopChanged: { volteController.setExperimentalVisible(top && top.objectName === "experimentalPage"); }
    onCreationCompleted: {
        volteController.confirmationNeeded.connect(function() { confirmation.show(); });
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
                    page.appNavigation = navigation;
                    navigation.push(page);
                }
            },
            ActionItem {
                title: navigation.t("status")
                enabled: !volteController.busy
                shortcuts: [ Shortcut { key: "R" } ]
                onTriggered: volteController.refresh()
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
                    text: volteController.deviceText + "  ·  " + volteController.carrierText
                    multiline: true
                    textStyle.fontSize: FontSize.Small
                    textFormat: TextFormat.Plain
                }
                Divider {}
                Label {
                    text: volteController.statusTitle
                    multiline: true
                    textStyle.fontSize: FontSize.XLarge
                    textStyle.fontWeight: FontWeight.W500
                    textFormat: TextFormat.Plain
                }
                Label {
                    text: volteController.statusMessage
                    visible: text.length > 0
                    multiline: true
                    textFormat: TextFormat.Plain
                }
                ActivityIndicator {
                    visible: volteController.busy || volteController.jobRunning || volteController.waitingForRoot
                    running: visible
                    preferredWidth: 72
                    preferredHeight: 72
                    horizontalAlignment: HorizontalAlignment.Center
                }
                Label {
                    text: volteController.jobText
                    visible: text.length > 0
                    multiline: true
                    textStyle.fontSize: FontSize.Small
                    textFormat: TextFormat.Plain
                }
                Container {
                    visible: volteController.primaryAction === "install" || volteController.model.state === "backup_required" || volteController.model.state === "needs_backup_location"
                    DropDown {
                        title: navigation.t("backup_title")
                        enabled: !volteController.busy && !volteController.jobRunning
                        options: [
                            Option { text: navigation.t("backup_internal"); value: "internal"; selected: volteController.backupLocation === "internal" },
                            Option { text: navigation.t("backup_sd"); value: "sdcard"; enabled: volteController.sdAvailable; selected: volteController.backupLocation === "sdcard" }
                        ]
                        onSelectedOptionChanged: { if (selectedOption) volteController.backupLocation = selectedOption.value; }
                    }
                    Label {
                        text: navigation.t(volteController.backupLocation === "sdcard" ? "backup_sd_note" : "backup_internal_note")
                        multiline: true
                        textStyle.fontSize: FontSize.Small
                        textFormat: TextFormat.Plain
                    }
                }
                Button {
                    text: volteController.primaryText
                    horizontalAlignment: HorizontalAlignment.Fill
                    enabled: !volteController.busy && volteController.allowed(volteController.primaryAction)
                    onClicked: {
                        if (volteController.primaryAction === "confirm-calls") navigation.push(callPage.createObject());
                        else volteController.primary();
                    }
                }
                Button {
                    text: navigation.t("confirm-calls")
                    horizontalAlignment: HorizontalAlignment.Fill
                    visible: { var state = volteController.model; return volteController.allowed("confirm-calls") && volteController.primaryAction !== "confirm-calls"; }
                    enabled: !volteController.busy && !volteController.jobRunning
                    onClicked: navigation.push(callPage.createObject())
                }
                Label {
                    text: volteController.notice
                    visible: text.length > 0
                    multiline: true
                    textStyle.fontSize: FontSize.Small
                    textFormat: TextFormat.Plain
                }
                Label {
                    text: navigation.t("export_path") + ": " + volteController.exportPath
                    visible: volteController.exportPath.length > 0
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
            title: volteController.confirmationTitle
            body: volteController.confirmationBody
            confirmButton.label: navigation.t("continue")
            cancelButton.label: navigation.t("cancel")
            onFinished: {
                if (result === SystemUiResult.ConfirmButtonSelection) volteController.confirmAction();
                else volteController.cancelConfirmation();
            }
        }
    ]
}
