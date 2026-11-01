import bb.cascades 1.4
import bb.cascades.pickers 1.0

Page {
    id: page
    property variant navigation
    function t(key) { var language = ui.language; return ui.label(key); }
    titleBar: TitleBar { title: page.t("advanced") }
    ScrollView {
        scrollViewProperties.scrollMode: ScrollMode.Vertical
        Container {
            leftPadding: 24
            rightPadding: 24
            topPadding: 12
            bottomPadding: 32
            Label { text: ui.statusTitle; multiline: true; textStyle.fontSize: FontSize.Large; textFormat: TextFormat.Plain }
            Label { text: ui.statusMessage; multiline: true; visible: text.length > 0; textFormat: TextFormat.Plain }
            Label { text: ui.jobText; multiline: true; visible: text.length > 0; textFormat: TextFormat.Plain }
            ActivityIndicator { visible: ui.busy || ui.jobRunning; running: visible; preferredHeight: 60; preferredWidth: 60 }
            Label { text: page.t("details"); textStyle.fontWeight: FontWeight.W500 }
            Label { text: ui.detailText; multiline: true; textStyle.fontSize: FontSize.Small; textFormat: TextFormat.Plain }
            Label { text: page.t("version") + ": " + ui.version; textStyle.fontSize: FontSize.Small }
            Divider {}
            DropDown {
                title: page.t("language")
                options: [
                    Option { text: "中文"; value: "zh"; selected: ui.language === "zh" },
                    Option { text: "English"; value: "en"; selected: ui.language === "en" }
                ]
                onSelectedOptionChanged: { if (selectedOption) ui.language = selectedOption.value; }
            }
            DropDown {
                title: page.t("backup_title")
                enabled: !ui.busy && !ui.jobRunning
                options: [
                    Option { text: page.t("backup_internal"); value: "internal"; selected: ui.backupLocation === "internal" },
                    Option { text: page.t("backup_sd"); value: "sdcard"; enabled: ui.sdAvailable; selected: ui.backupLocation === "sdcard" }
                ]
                onSelectedOptionChanged: { if (selectedOption) ui.backupLocation = selectedOption.value; }
            }
            Label { text: page.t(ui.backupLocation === "sdcard" ? "backup_sd_note" : "backup_internal_note"); multiline: true; textStyle.fontSize: FontSize.Small; textFormat: TextFormat.Plain }
            Divider {}
            Button {
                text: page.t("bundled_update")
                horizontalAlignment: HorizontalAlignment.Fill
                visible: ui.canApplyBundledUpdate
                enabled: !ui.busy && ui.allowed("update")
                onClicked: ui.applyBundledUpdate()
            }
            Label { text: page.t("offline_update"); textStyle.fontWeight: FontWeight.W500 }
            Label { text: ui.packageName; multiline: true; textStyle.fontSize: FontSize.Small; textFormat: TextFormat.Plain }
            Button {
                text: page.t("pick_package")
                horizontalAlignment: HorizontalAlignment.Fill
                enabled: !ui.busy && !ui.jobRunning
                onClicked: packagePicker.open()
            }
            Button {
                text: page.t("update")
                horizontalAlignment: HorizontalAlignment.Fill
                enabled: ui.hasPackage && !ui.busy && ui.allowed("update")
                onClicked: ui.requestAction("update")
            }
            Button {
                text: page.t("check_update")
                horizontalAlignment: HorizontalAlignment.Fill
                enabled: !ui.busy && !ui.jobRunning
                onClicked: ui.checkUpdate()
            }
            Button {
                text: page.t("download_update")
                horizontalAlignment: HorizontalAlignment.Fill
                visible: ui.hasUpdate
                enabled: !ui.busy && ui.allowed("update")
                onClicked: ui.downloadUpdate()
            }
            Label { text: ui.notice; visible: text.length > 0; multiline: true; textStyle.fontSize: FontSize.Small; textFormat: TextFormat.Plain }
            Divider {}
            Button { text: page.t("export_backup"); horizontalAlignment: HorizontalAlignment.Fill; enabled: !ui.busy && ui.allowed("export"); onClicked: ui.exportBackup() }
            Button { text: page.t("export"); horizontalAlignment: HorizontalAlignment.Fill; enabled: !ui.busy && ui.allowed("export"); onClicked: ui.requestAction("export") }
            Button { text: page.t("compatibility"); horizontalAlignment: HorizontalAlignment.Fill; enabled: !ui.busy && ui.allowed("compatibility"); onClicked: ui.requestAction("compatibility") }
            Button { text: page.t("enable"); horizontalAlignment: HorizontalAlignment.Fill; enabled: !ui.busy && ui.allowed("enable"); onClicked: ui.requestAction("enable") }
            Button { text: page.t("disable"); horizontalAlignment: HorizontalAlignment.Fill; enabled: !ui.busy && ui.allowed("disable"); onClicked: ui.requestAction("disable") }
            Button { text: page.t("rollback"); horizontalAlignment: HorizontalAlignment.Fill; enabled: !ui.busy && ui.allowed("rollback"); onClicked: ui.requestAction("rollback") }
            Button { text: page.t("uninstall"); horizontalAlignment: HorizontalAlignment.Fill; enabled: !ui.busy && ui.allowed("uninstall"); onClicked: ui.requestAction("uninstall") }
            Button {
                text: page.t("legacy")
                horizontalAlignment: HorizontalAlignment.Fill
                enabled: !ui.busy && !ui.jobRunning
                onClicked: navigation.push(experimentalPage.createObject())
            }
        }
    }
    attachedObjects: [
        ComponentDefinition { id: experimentalPage; source: "Experimental.qml" },
        FilePicker {
            id: packagePicker
            title: page.t("pick_package")
            type: FileType.Other
            mode: FilePickerMode.Picker
            filter: ["*.zip"]
            directories: ["/accounts/1000/shared/downloads", "/accounts/1000/removable/sdcard"]
            onFileSelected: { if (selectedFiles.length === 1) ui.choosePackage(selectedFiles[0]); }
        }
    ]
}
