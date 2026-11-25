import bb.cascades 1.4
import bb.cascades.pickers 1.0

Page {
    id: page
    property variant appNavigation
    property bool advancedOpen: false
    function t(key) { var language = volteController.language; return volteController.label(key); }
    function allows(action) { var model = volteController.model; return volteController.allowed(action); }
    titleBar: TitleBar { title: page.t("advanced") }
    actions: [
        ActionItem {
            title: page.t("status")
            enabled: !volteController.busy && !volteController.operationInProgress
            ActionBar.placement: ActionBarPlacement.OnBar
            shortcuts: [ Shortcut { key: "R" } ]
            onTriggered: volteController.refresh()
        }
    ]
    ScrollView {
        scrollViewProperties.scrollMode: ScrollMode.Vertical
        Container {
            leftPadding: 24
            rightPadding: 24
            topPadding: 12
            bottomPadding: 32
            Label { text: volteController.statusTitle; multiline: true; textStyle.fontSize: FontSize.Large; textFormat: TextFormat.Plain }
            Label { text: volteController.statusMessage; multiline: true; visible: text.length > 0; textFormat: TextFormat.Plain }
            Label { text: volteController.cachedStatusText; multiline: true; visible: text.length > 0; textStyle.fontSize: FontSize.Small; textFormat: TextFormat.Plain }
            Label { text: volteController.jobText; multiline: true; visible: text.length > 0; textFormat: TextFormat.Plain }
            Label { text: page.t("export_path") + ": " + volteController.exportPath; visible: volteController.exportPath.length > 0; multiline: true; textStyle.fontSize: FontSize.Small; textFormat: TextFormat.Plain }
            ActivityIndicator { visible: volteController.activityVisible; running: visible; preferredHeight: 60; preferredWidth: 60 }
            Label { text: page.t("app_version") + ": " + volteController.version + "  ·  " + page.t("phone_service") + ": " + volteController.phoneServiceText; multiline: true; textStyle.fontSize: FontSize.Small; textFormat: TextFormat.Plain }
            Button {
                text: page.t("pair_title")
                horizontalAlignment: HorizontalAlignment.Fill
                enabled: !volteController.busy && !volteController.operationInProgress && !pairingController.busy
                onClicked: page.appNavigation.push(pairingPage.createObject())
            }
            Label { text: page.t("pair_optional"); multiline: true; textStyle.fontSize: FontSize.Small; textFormat: TextFormat.Plain }
            Divider {}
            DropDown {
                title: page.t("language")
                options: [
                    Option { text: "中文"; value: "zh"; selected: volteController.language === "zh" },
                    Option { text: page.t("language_english"); value: "en"; selected: volteController.language === "en" }
                ]
                onSelectedOptionChanged: { if (selectedOption) volteController.language = selectedOption.value; }
            }
            DropDown {
                title: page.t("backup_title")
                enabled: !volteController.busy && !volteController.jobRunning
                options: [
                    Option { text: page.t("backup_internal"); value: "internal"; selected: volteController.backupLocation === "internal" },
                    Option { text: page.t("backup_sd"); value: "sdcard"; enabled: volteController.sdAvailable; selected: volteController.backupLocation === "sdcard" }
                ]
                onSelectedOptionChanged: { if (selectedOption) volteController.backupLocation = selectedOption.value; }
            }
            Label { text: page.t(volteController.backupLocation === "sdcard" ? "backup_sd_note" : "backup_internal_note"); multiline: true; textStyle.fontSize: FontSize.Small; textFormat: TextFormat.Plain }
            Divider {}
            Button {
                text: page.t("bundled_update")
                horizontalAlignment: HorizontalAlignment.Fill
                visible: volteController.canApplyBundledUpdate
                enabled: page.allows("update")
                onClicked: volteController.applyBundledUpdate()
            }
            Button {
                text: page.t("check_update")
                horizontalAlignment: HorizontalAlignment.Fill
                enabled: !volteController.busy && !volteController.jobRunning
                onClicked: volteController.checkUpdate()
            }
            Button {
                text: page.t("download_update")
                horizontalAlignment: HorizontalAlignment.Fill
                visible: volteController.hasUpdate
                enabled: page.allows("update")
                onClicked: volteController.downloadUpdate()
            }
            Button {
                text: page.t("cancel_update_transfer")
                horizontalAlignment: HorizontalAlignment.Fill
                visible: volteController.networkTransferInProgress
                onClicked: volteController.cancelUpdateTransfer()
            }
            Label { text: volteController.updateBlockMessage; visible: text.length > 0; multiline: true; textFormat: TextFormat.Plain }
            Label { text: volteController.updateFeedback; visible: text.length > 0; multiline: true; textStyle.fontSize: FontSize.Small; textFormat: TextFormat.Plain }
            Divider {}
            Button {
                text: page.t("confirm-calls")
                horizontalAlignment: HorizontalAlignment.Fill
                visible: page.allows("confirm-calls")
                enabled: !volteController.busy && !volteController.jobRunning
                onClicked: page.appNavigation.push(callPage.createObject())
            }
            Button { text: page.t("export_backup"); horizontalAlignment: HorizontalAlignment.Fill; enabled: !volteController.busy && volteController.canExportBackup; onClicked: volteController.exportBackup() }
            Button { text: page.t("export"); horizontalAlignment: HorizontalAlignment.Fill; enabled: page.allows("export"); onClicked: volteController.requestAction("export") }
            Button { text: page.t("enable"); horizontalAlignment: HorizontalAlignment.Fill; enabled: page.allows("enable"); onClicked: volteController.requestAction("enable") }
            Button { text: page.t("restore_network"); horizontalAlignment: HorizontalAlignment.Fill; enabled: page.allows("disable"); onClicked: volteController.requestAction("disable") }
            Label { text: page.t("restore_network_help"); visible: page.allows("disable"); multiline: true; textStyle.fontSize: FontSize.Small; textFormat: TextFormat.Plain }
            Button { text: page.t("uninstall"); horizontalAlignment: HorizontalAlignment.Fill; enabled: page.allows("uninstall"); onClicked: volteController.requestAction("uninstall") }
            Divider {}
            Button {
                text: page.t(page.advancedOpen ? "advanced_less" : "advanced_more")
                horizontalAlignment: HorizontalAlignment.Fill
                onClicked: page.advancedOpen = !page.advancedOpen
            }
            Container {
                visible: page.advancedOpen
                topPadding: 12
                Label { text: page.t("details"); textStyle.fontWeight: FontWeight.W500 }
                Label { text: volteController.detailText; multiline: true; textStyle.fontSize: FontSize.Small; textFormat: TextFormat.Plain }
                Label { text: page.t("runtime_version") + ": " + volteController.runtimeVersionText; textStyle.fontSize: FontSize.Small }
                Divider {}
                Label { text: page.t("offline_update"); textStyle.fontWeight: FontWeight.W500 }
                Label { text: volteController.packageName; multiline: true; textStyle.fontSize: FontSize.Small; textFormat: TextFormat.Plain }
                Button {
                    text: page.t("pick_package")
                    horizontalAlignment: HorizontalAlignment.Fill
                    enabled: !volteController.busy && !volteController.jobRunning
                    onClicked: { if (volteController.beginPackageSelection()) packagePicker.open(); }
                }
                Button {
                    text: page.t("update")
                    horizontalAlignment: HorizontalAlignment.Fill
                    enabled: volteController.hasPackage && page.allows("update")
                    onClicked: volteController.requestAction("update")
                }
                Button { text: page.t("rollback"); horizontalAlignment: HorizontalAlignment.Fill; enabled: page.allows("rollback"); onClicked: volteController.requestAction("rollback") }
                Button { text: page.t("compatibility"); horizontalAlignment: HorizontalAlignment.Fill; enabled: page.allows("compatibility"); onClicked: volteController.requestAction("compatibility") }
                Button {
                    text: page.t("overseas_title")
                    horizontalAlignment: HorizontalAlignment.Fill
                    enabled: volteController.canManageOverseas
                    onClicked: page.appNavigation.push(overseasPage.createObject())
                }
                Button {
                    text: page.t("legacy")
                    horizontalAlignment: HorizontalAlignment.Fill
                    enabled: !volteController.busy && !volteController.jobRunning
                    onClicked: page.appNavigation.push(experimentalPage.createObject())
                }
            }
        }
    }
    attachedObjects: [
        ComponentDefinition { id: pairingPage; source: "Pairing.qml" },
        ComponentDefinition { id: experimentalPage; source: "Experimental.qml" },
        ComponentDefinition { id: callPage; source: "CallCheck.qml" },
        ComponentDefinition { id: overseasPage; source: "OverseasCarrier.qml" },
        FilePicker {
            id: packagePicker
            title: page.t("pick_package")
            type: FileType.Other
            mode: FilePickerMode.Picker
            filter: ["*.zip"]
            directories: ["/accounts/1000/shared/downloads", "/accounts/1000/removable/sdcard"]
            onFileSelected: {
                if (selectedFiles.length === 1) volteController.choosePackage(selectedFiles[0]);
                volteController.endPackageSelection();
            }
            onCanceled: volteController.endPackageSelection()
            onPickerClosed: volteController.packagePickerClosed()
            onError: volteController.packagePickerError()
        }
    ]
}
