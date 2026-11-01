import bb.cascades 1.4

Page {
    id: page
    function t(key) { var language = ui.language; return ui.label(key); }
    titleBar: TitleBar { title: page.t("legacy") }
    ScrollView {
        scrollViewProperties.scrollMode: ScrollMode.Vertical
        Container {
            leftPadding: 24
            rightPadding: 24
            topPadding: 20
            bottomPadding: 32
            Label { text: page.t("legacy_note"); multiline: true; textFormat: TextFormat.Plain }
            Label { text: ui.deviceText + " / " + ui.carrierText; multiline: true; textFormat: TextFormat.Plain }
            DropDown {
                id: profile
                title: page.t("profile")
                enabled: !ui.busy && !ui.jobRunning
                options: [
                    Option { text: page.t("profile_mobile"); value: "china-mobile"; selected: ui.legacyProfile === "china-mobile" },
                    Option { text: page.t("profile_unicom"); value: "china-unicom"; selected: ui.legacyProfile === "china-unicom" },
                    Option { text: page.t("profile_telecom"); value: "china-telecom"; selected: ui.legacyProfile === "china-telecom" },
                    Option { text: page.t("profile_telecom_46011"); value: "china-telecom-46011"; selected: ui.legacyProfile === "china-telecom-46011" },
                    Option { text: "SQC100-1 / " + page.t("profile_mobile"); value: "variant-trial-sqc100-1-mobile"; selected: ui.legacyProfile === "variant-trial-sqc100-1-mobile" },
                    Option { text: "SQC100-1 / " + page.t("profile_telecom"); value: "variant-trial-sqc100-1-telecom"; selected: ui.legacyProfile === "variant-trial-sqc100-1-telecom" },
                    Option { text: "SQC100-1 / " + page.t("profile_unicom"); value: "variant-trial-sqc100-1-unicom"; selected: ui.legacyProfile === "variant-trial-sqc100-1-unicom" },
                    Option { text: "SQC100-3 / " + page.t("profile_mobile"); value: "variant-trial-sqc100-3-mobile"; selected: ui.legacyProfile === "variant-trial-sqc100-3-mobile" },
                    Option { text: "SQC100-3 / " + page.t("profile_telecom"); value: "variant-trial-sqc100-3-telecom"; selected: ui.legacyProfile === "variant-trial-sqc100-3-telecom" },
                    Option { text: "SQC100-3 / " + page.t("profile_unicom"); value: "variant-trial-sqc100-3-unicom"; selected: ui.legacyProfile === "variant-trial-sqc100-3-unicom" },
                    Option { text: "SQC100-4 / " + page.t("profile_telecom"); value: "variant-trial-sqc100-4-telecom"; selected: ui.legacyProfile === "variant-trial-sqc100-4-telecom" },
                    Option { text: "SQC100-4 / " + page.t("profile_unicom"); value: "variant-trial-sqc100-4-unicom"; selected: ui.legacyProfile === "variant-trial-sqc100-4-unicom" },
                    Option { text: "SQC100-5 / " + page.t("profile_mobile"); value: "variant-trial-sqc100-5-mobile"; selected: ui.legacyProfile === "variant-trial-sqc100-5-mobile" },
                    Option { text: "SQC100-5 / " + page.t("profile_telecom"); value: "variant-trial-sqc100-5-telecom"; selected: ui.legacyProfile === "variant-trial-sqc100-5-telecom" },
                    Option { text: "SQC100-5 / " + page.t("profile_unicom"); value: "variant-trial-sqc100-5-unicom"; selected: ui.legacyProfile === "variant-trial-sqc100-5-unicom" },
                    Option { text: "SQN100-1 / " + page.t("profile_telecom"); value: "variant-trial-sqn100-1-telecom"; selected: ui.legacyProfile === "variant-trial-sqn100-1-telecom" },
                    Option { text: "SQN100-5 / " + page.t("profile_telecom"); value: "variant-trial-sqn100-5-telecom"; selected: ui.legacyProfile === "variant-trial-sqn100-5-telecom" },
                    Option { text: "SQW100-1 / " + page.t("profile_mobile") + " / " + page.t("trial_read_only"); value: "variant-trial-sqw100-1-mobile"; selected: ui.legacyProfile === "variant-trial-sqw100-1-mobile" },
                    Option { text: "SQW100-1 / " + page.t("profile_telecom") + " / " + page.t("trial_read_only"); value: "variant-trial-sqw100-1-telecom"; selected: ui.legacyProfile === "variant-trial-sqw100-1-telecom" },
                    Option { text: "SQW100-1 / " + page.t("profile_unicom") + " / " + page.t("trial_read_only"); value: "variant-trial-sqw100-1-unicom"; selected: ui.legacyProfile === "variant-trial-sqw100-1-unicom" },
                    Option { text: "SQW100-3 / " + page.t("profile_mobile") + " / " + page.t("trial_read_only"); value: "variant-trial-sqw100-3-mobile"; selected: ui.legacyProfile === "variant-trial-sqw100-3-mobile" },
                    Option { text: "SQW100-3 / " + page.t("profile_telecom") + " / " + page.t("trial_read_only"); value: "variant-trial-sqw100-3-telecom"; selected: ui.legacyProfile === "variant-trial-sqw100-3-telecom" },
                    Option { text: "SQW100-3 / " + page.t("profile_unicom") + " / " + page.t("trial_read_only"); value: "variant-trial-sqw100-3-unicom"; selected: ui.legacyProfile === "variant-trial-sqw100-3-unicom" }
                ]
                onSelectedOptionChanged: { if (selectedOption) ui.legacyProfile = selectedOption.value; }
            }
            Button { text: page.t("legacy-inspect"); horizontalAlignment: HorizontalAlignment.Fill; enabled: !ui.busy && !ui.jobRunning; onClicked: ui.legacyAction("legacy-inspect", profile.selectedOption.value) }
            Label { text: ui.statusTitle; multiline: true; textStyle.fontSize: FontSize.Large; textFormat: TextFormat.Plain }
            Label { text: ui.statusMessage; multiline: true; textFormat: TextFormat.Plain }
            Label { text: ui.detailText; multiline: true; textStyle.fontSize: FontSize.Small; textFormat: TextFormat.Plain }
            Label { text: ui.jobText; visible: text.length > 0; multiline: true; textFormat: TextFormat.Plain }
            Button { text: page.t("legacy-install"); horizontalAlignment: HorizontalAlignment.Fill; enabled: !ui.busy && ui.allowed("legacy-install"); onClicked: ui.legacyAction("legacy-install", profile.selectedOption.value) }
            Button { text: page.t("legacy-start"); horizontalAlignment: HorizontalAlignment.Fill; enabled: !ui.busy && ui.allowed("legacy-start"); onClicked: ui.legacyAction("legacy-start", profile.selectedOption.value) }
            Button { text: page.t("legacy-stop"); horizontalAlignment: HorizontalAlignment.Fill; enabled: !ui.busy && ui.allowed("legacy-stop"); onClicked: ui.legacyAction("legacy-stop", profile.selectedOption.value) }
            Button { text: page.t("legacy-update"); horizontalAlignment: HorizontalAlignment.Fill; enabled: !ui.busy && ui.allowed("legacy-update"); onClicked: ui.legacyAction("legacy-update", profile.selectedOption.value) }
            Button { text: page.t("legacy-uninstall"); horizontalAlignment: HorizontalAlignment.Fill; enabled: !ui.busy && ui.allowed("legacy-uninstall"); onClicked: ui.legacyAction("legacy-uninstall", profile.selectedOption.value) }
            Button { text: page.t("compatibility"); horizontalAlignment: HorizontalAlignment.Fill; enabled: !ui.busy && ui.allowed("compatibility"); onClicked: ui.requestAction("compatibility") }
        }
    }
}
