import bb.cascades 1.4
import bb.cascades.pickers 1.0

Page {
    id: page
    property variant appNavigation
    function t(key) { var language = volteController.language; return volteController.label(key); }
    titleBar: TitleBar { title: page.t("advanced") }
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
            ActivityIndicator { visible: volteController.activityVisible; running: visible; preferredHeight: 60; preferredWidth: 60 }
            Button { text: page.t("status"); horizontalAlignment: HorizontalAlignment.Fill; enabled: !volteController.busy && !volteController.operationInProgress; onClicked: volteController.refresh() }
            Label { text: page.t("details"); textStyle.fontWeight: FontWeight.W500 }
            Label { text: volteController.detailText; multiline: true; textStyle.fontSize: FontSize.Small; textFormat: TextFormat.Plain }
            Label { text: page.t("app_version") + ": " + volteController.version; textStyle.fontSize: FontSize.Small }
            Label { text: page.t("runtime_version") + ": " + volteController.runtimeVersionText; textStyle.fontSize: FontSize.Small }
            Label { text: page.t("phone_service") + ": " + volteController.phoneServiceText; textStyle.fontSize: FontSize.Small }
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
                enabled: !volteController.busy && volteController.allowed("update")
                onClicked: volteController.applyBundledUpdate()
            }
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
                enabled: volteController.hasPackage && !volteController.busy && volteController.allowed("update")
                onClicked: volteController.requestAction("update")
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
                enabled: !volteController.busy && volteController.allowed("update")
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
                text: page.t("pair_title")
                horizontalAlignment: HorizontalAlignment.Fill
                enabled: !volteController.busy && !volteController.operationInProgress && !pairingController.busy
                onClicked: page.appNavigation.push(pairingPage.createObject())
            }
            Label { text: page.t("pair_optional"); multiline: true; textStyle.fontSize: FontSize.Small; textFormat: TextFormat.Plain }
            Button { text: page.t("export_backup"); horizontalAlignment: HorizontalAlignment.Fill; enabled: !volteController.busy && volteController.canExportBackup; onClicked: volteController.exportBackup() }
            Button { text: page.t("export"); horizontalAlignment: HorizontalAlignment.Fill; enabled: !volteController.busy && volteController.allowed("export"); onClicked: volteController.requestAction("export") }
            Button { text: page.t("compatibility"); horizontalAlignment: HorizontalAlignment.Fill; enabled: !volteController.busy && volteController.allowed("compatibility"); onClicked: volteController.requestAction("compatibility") }
            Button { text: page.t("enable"); horizontalAlignment: HorizontalAlignment.Fill; enabled: !volteController.busy && volteController.allowed("enable"); onClicked: volteController.requestAction("enable") }
            Button { text: page.t("restore_network"); horizontalAlignment: HorizontalAlignment.Fill; enabled: !volteController.busy && volteController.allowed("disable"); onClicked: volteController.requestAction("disable") }
            Label { text: page.t("restore_network_help"); multiline: true; textStyle.fontSize: FontSize.Small; textFormat: TextFormat.Plain }
            Button { text: page.t("rollback"); horizontalAlignment: HorizontalAlignment.Fill; enabled: !volteController.busy && volteController.allowed("rollback"); onClicked: volteController.requestAction("rollback") }
            Button { text: page.t("uninstall"); horizontalAlignment: HorizontalAlignment.Fill; enabled: !volteController.busy && volteController.allowed("uninstall"); onClicked: volteController.requestAction("uninstall") }
            Button {
                text: page.t("legacy")
                horizontalAlignment: HorizontalAlignment.Fill
                enabled: !volteController.busy && !volteController.jobRunning
                onClicked: page.appNavigation.push(experimentalPage.createObject())
            }
        }
    }
    attachedObjects: [
        ComponentDefinition { id: pairingPage; source: "Pairing.qml" },
        ComponentDefinition { id: experimentalPage; source: "Experimental.qml" },
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
