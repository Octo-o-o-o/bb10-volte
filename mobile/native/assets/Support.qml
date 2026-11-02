import bb.cascades 1.4

Page {
    id: supportPage
    property variant appNavigation
    property bool coffeeExpanded: false
    property string provider: "alipay"
    property string amount: "custom"
    function t(key) { var language = volteController.language; return volteController.label(key); }
    onCreationCompleted: supportController.reset()
    titleBar: TitleBar {
        title: "OctoLab"
        acceptAction: ActionItem {
            title: supportPage.t("close")
            onTriggered: supportPage.appNavigation.pop()
        }
    }
    ScrollView {
        horizontalAlignment: HorizontalAlignment.Fill
        verticalAlignment: VerticalAlignment.Fill
        scrollViewProperties.scrollMode: ScrollMode.Vertical
        Container {
            horizontalAlignment: HorizontalAlignment.Fill
            background: Color.create("#F5F4EF")
            leftPadding: 32
            rightPadding: 32
            topPadding: 36
            bottomPadding: 40
            Container {
                layout: StackLayout { orientation: LayoutOrientation.LeftToRight }
                ImageView {
                    imageSource: "asset:///support/octoooo-favicon.png"
                    preferredWidth: 48
                    preferredHeight: 48
                    verticalAlignment: VerticalAlignment.Center
                }
                Label {
                    text: supportPage.t("support_kicker")
                    textStyle.fontSize: FontSize.Small
                    textStyle.color: Color.create("#627169")
                    verticalAlignment: VerticalAlignment.Center
                    textFormat: TextFormat.Plain
                }
            }
            Label {
                topMargin: 28
                text: supportPage.t("support_title")
                multiline: true
                textStyle.fontSize: FontSize.XXLarge
                textStyle.fontWeight: FontWeight.W500
                textStyle.color: Color.create("#233D32")
                textFormat: TextFormat.Plain
            }
            Label {
                text: supportPage.t("support_story")
                multiline: true
                textStyle.color: Color.create("#536159")
                textStyle.fontSize: FontSize.Small
                textFormat: TextFormat.Plain
            }
            Container {
                topMargin: 24
                layout: StackLayout { orientation: LayoutOrientation.LeftToRight }
                Button {
                    text: supportPage.t("support_star")
                    layoutProperties: StackLayoutProperties { spaceQuota: 1 }
                    enabled: !supportController.opening
                    onClicked: supportController.openLink("github")
                }
                Button {
                    text: supportPage.t("support_studio")
                    layoutProperties: StackLayoutProperties { spaceQuota: 1 }
                    enabled: !supportController.opening
                    onClicked: supportController.openLink("studio")
                }
            }
            Label {
                text: supportPage.t("support_star_note")
                multiline: true
                textStyle.fontSize: FontSize.Small
                textStyle.color: Color.create("#627169")
                textFormat: TextFormat.Plain
            }
            Container {
                visible: supportController.messageKey.length > 0
                Label {
                    text: supportPage.t(supportController.messageKey)
                    multiline: true
                    textStyle.fontSize: FontSize.Small
                    textStyle.color: Color.create("#536159")
                    textFormat: TextFormat.Plain
                }
                Label {
                    text: supportController.lastLink
                    multiline: true
                    textStyle.fontSize: FontSize.Small
                    textStyle.color: Color.create("#233D32")
                    textFormat: TextFormat.Plain
                }
                Button {
                    text: supportPage.t("support_copy")
                    enabled: !supportController.opening
                    onClicked: supportController.copyLink()
                }
            }
            Divider { topMargin: 28; bottomMargin: 20 }
            Button {
                text: supportPage.t(coffeeExpanded ? "support_coffee_close" : "support_coffee")
                horizontalAlignment: HorizontalAlignment.Fill
                onClicked: supportPage.coffeeExpanded = !supportPage.coffeeExpanded
            }
            Label {
                text: supportPage.t("support_optional")
                multiline: true
                textStyle.fontSize: FontSize.Small
                textStyle.color: Color.create("#627169")
                textFormat: TextFormat.Plain
            }
            Container {
                visible: supportPage.coffeeExpanded
                topMargin: 16
                leftPadding: 24
                rightPadding: 24
                topPadding: 24
                bottomPadding: 28
                background: Color.White
                SegmentedControl {
                    options: [
                        Option { text: supportPage.t("support_alipay"); value: "alipay"; selected: true },
                        Option { text: supportPage.t("support_wechat"); value: "wechat" }
                    ]
                    onSelectedOptionChanged: { if (selectedOption) supportPage.provider = selectedOption.value; }
                }
                DropDown {
                    title: supportPage.t("support_amount")
                    options: [
                        Option { text: supportPage.t("support_custom"); value: "custom"; selected: true },
                        Option { text: "CNY 9.90"; value: "9_90" },
                        Option { text: "CNY 19.90"; value: "19_90" },
                        Option { text: "CNY 29.90"; value: "29_90" }
                    ]
                    onSelectedOptionChanged: { if (selectedOption) supportPage.amount = selectedOption.value; }
                }
                ImageView {
                    topMargin: 24
                    bottomMargin: 16
                    imageSource: "asset:///support/" + supportPage.provider + "-" + supportPage.amount + ".png"
                    scalingMethod: ScalingMethod.None
                    preferredWidth: 264
                    preferredHeight: 264
                    minWidth: 264
                    minHeight: 264
                    maxWidth: 264
                    maxHeight: 264
                    horizontalAlignment: HorizontalAlignment.Center
                    accessibility.name: supportPage.t("support_qr")
                }
                Label {
                    text: supportPage.t(supportPage.amount === "custom" ? "support_scan_custom" : "support_scan_fixed")
                    multiline: true
                    textStyle.fontSize: FontSize.Small
                    textStyle.color: Color.create("#536159")
                    textFormat: TextFormat.Plain
                }
            }
            Label {
                topMargin: 24
                text: "BB10 VoLTE · " + volteController.version + " · MIT"
                textStyle.fontSize: FontSize.Small
                textStyle.color: Color.create("#627169")
                textFormat: TextFormat.Plain
            }
        }
    }
}
