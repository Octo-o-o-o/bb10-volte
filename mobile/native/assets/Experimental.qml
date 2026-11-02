import bb.cascades 1.4

Page {
    id: page
    objectName: "experimentalPage"
    function t(key) { var language = volteController.language; return volteController.label(key); }
    titleBar: TitleBar { title: page.t("legacy") }
    ScrollView {
        scrollViewProperties.scrollMode: ScrollMode.Vertical
        Container {
            leftPadding: 24
            rightPadding: 24
            topPadding: 20
            bottomPadding: 32
            Label { text: page.t("legacy_note"); multiline: true; textFormat: TextFormat.Plain }
            Label { text: volteController.deviceText + " / " + volteController.carrierText; multiline: true; textFormat: TextFormat.Plain }
            DropDown {
                id: profile
                title: page.t("profile")
                enabled: !volteController.busy && !volteController.jobRunning
                options: [
                    Option { text: page.t("profile_mobile"); value: "china-mobile"; selected: volteController.legacyProfile === "china-mobile" },
                    Option { text: page.t("profile_unicom"); value: "china-unicom"; selected: volteController.legacyProfile === "china-unicom" },
                    Option { text: page.t("profile_telecom"); value: "china-telecom"; selected: volteController.legacyProfile === "china-telecom" },
                    Option { text: page.t("profile_telecom_46011"); value: "china-telecom-46011"; selected: volteController.legacyProfile === "china-telecom-46011" },
                    Option { text: "SQC100-1 / " + page.t("profile_mobile"); value: "variant-trial-sqc100-1-mobile"; selected: volteController.legacyProfile === "variant-trial-sqc100-1-mobile" },
                    Option { text: "SQC100-1 / " + page.t("profile_telecom"); value: "variant-trial-sqc100-1-telecom"; selected: volteController.legacyProfile === "variant-trial-sqc100-1-telecom" },
                    Option { text: "SQC100-1 / " + page.t("profile_unicom"); value: "variant-trial-sqc100-1-unicom"; selected: volteController.legacyProfile === "variant-trial-sqc100-1-unicom" },
                    Option { text: "SQC100-3 / " + page.t("profile_mobile"); value: "variant-trial-sqc100-3-mobile"; selected: volteController.legacyProfile === "variant-trial-sqc100-3-mobile" },
                    Option { text: "SQC100-3 / " + page.t("profile_telecom"); value: "variant-trial-sqc100-3-telecom"; selected: volteController.legacyProfile === "variant-trial-sqc100-3-telecom" },
                    Option { text: "SQC100-3 / " + page.t("profile_unicom"); value: "variant-trial-sqc100-3-unicom"; selected: volteController.legacyProfile === "variant-trial-sqc100-3-unicom" },
                    Option { text: "SQC100-4 / " + page.t("profile_telecom"); value: "variant-trial-sqc100-4-telecom"; selected: volteController.legacyProfile === "variant-trial-sqc100-4-telecom" },
                    Option { text: "SQC100-4 / " + page.t("profile_unicom"); value: "variant-trial-sqc100-4-unicom"; selected: volteController.legacyProfile === "variant-trial-sqc100-4-unicom" },
                    Option { text: "SQC100-5 / " + page.t("profile_mobile"); value: "variant-trial-sqc100-5-mobile"; selected: volteController.legacyProfile === "variant-trial-sqc100-5-mobile" },
                    Option { text: "SQC100-5 / " + page.t("profile_telecom"); value: "variant-trial-sqc100-5-telecom"; selected: volteController.legacyProfile === "variant-trial-sqc100-5-telecom" },
                    Option { text: "SQC100-5 / " + page.t("profile_unicom"); value: "variant-trial-sqc100-5-unicom"; selected: volteController.legacyProfile === "variant-trial-sqc100-5-unicom" },
                    Option { text: "SQN100-1 / " + page.t("profile_telecom"); value: "variant-trial-sqn100-1-telecom"; selected: volteController.legacyProfile === "variant-trial-sqn100-1-telecom" },
                    Option { text: "SQN100-5 / " + page.t("profile_telecom"); value: "variant-trial-sqn100-5-telecom"; selected: volteController.legacyProfile === "variant-trial-sqn100-5-telecom" },
                    Option { text: "SQW100-1 / " + page.t("profile_mobile") + " / " + page.t("trial_read_only"); value: "variant-trial-sqw100-1-mobile"; selected: volteController.legacyProfile === "variant-trial-sqw100-1-mobile" },
                    Option { text: "SQW100-1 / " + page.t("profile_telecom") + " / " + page.t("trial_read_only"); value: "variant-trial-sqw100-1-telecom"; selected: volteController.legacyProfile === "variant-trial-sqw100-1-telecom" },
                    Option { text: "SQW100-1 / " + page.t("profile_unicom") + " / " + page.t("trial_read_only"); value: "variant-trial-sqw100-1-unicom"; selected: volteController.legacyProfile === "variant-trial-sqw100-1-unicom" },
                    Option { text: "SQW100-3 / " + page.t("profile_mobile") + " / " + page.t("trial_read_only"); value: "variant-trial-sqw100-3-mobile"; selected: volteController.legacyProfile === "variant-trial-sqw100-3-mobile" },
                    Option { text: "SQW100-3 / " + page.t("profile_telecom") + " / " + page.t("trial_read_only"); value: "variant-trial-sqw100-3-telecom"; selected: volteController.legacyProfile === "variant-trial-sqw100-3-telecom" },
                    Option { text: "SQW100-3 / " + page.t("profile_unicom") + " / " + page.t("trial_read_only"); value: "variant-trial-sqw100-3-unicom"; selected: volteController.legacyProfile === "variant-trial-sqw100-3-unicom" }
                ]
                onSelectedOptionChanged: { if (selectedOption) volteController.legacyProfile = selectedOption.value; }
            }
            Button { text: page.t("legacy-inspect"); horizontalAlignment: HorizontalAlignment.Fill; enabled: !volteController.busy && !volteController.jobRunning; onClicked: volteController.legacyAction("legacy-inspect", profile.selectedOption.value) }
            Label { text: volteController.statusTitle; multiline: true; textStyle.fontSize: FontSize.Large; textFormat: TextFormat.Plain }
            Label { text: volteController.statusMessage; multiline: true; textFormat: TextFormat.Plain }
            Label { text: volteController.detailText; multiline: true; textStyle.fontSize: FontSize.Small; textFormat: TextFormat.Plain }
            Label { text: volteController.jobText; visible: text.length > 0; multiline: true; textFormat: TextFormat.Plain }
            Button { text: page.t("legacy-install"); horizontalAlignment: HorizontalAlignment.Fill; enabled: !volteController.busy && volteController.allowed("legacy-install"); onClicked: volteController.legacyAction("legacy-install", profile.selectedOption.value) }
            Button { text: page.t("legacy-start"); horizontalAlignment: HorizontalAlignment.Fill; enabled: !volteController.busy && volteController.allowed("legacy-start"); onClicked: volteController.legacyAction("legacy-start", profile.selectedOption.value) }
            Button { text: page.t("legacy-stop"); horizontalAlignment: HorizontalAlignment.Fill; enabled: !volteController.busy && volteController.allowed("legacy-stop"); onClicked: volteController.legacyAction("legacy-stop", profile.selectedOption.value) }
            Button { text: page.t("legacy-update"); horizontalAlignment: HorizontalAlignment.Fill; enabled: !volteController.busy && volteController.allowed("legacy-update"); onClicked: volteController.legacyAction("legacy-update", profile.selectedOption.value) }
            Button { text: page.t("legacy-uninstall"); horizontalAlignment: HorizontalAlignment.Fill; enabled: !volteController.busy && volteController.allowed("legacy-uninstall"); onClicked: volteController.legacyAction("legacy-uninstall", profile.selectedOption.value) }
            Button { text: page.t("compatibility"); horizontalAlignment: HorizontalAlignment.Fill; enabled: !volteController.busy && volteController.allowed("compatibility"); onClicked: volteController.requestAction("compatibility") }
        }
    }
}
