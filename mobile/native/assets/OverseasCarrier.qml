import bb.cascades 1.4

Page {
    id: page
    objectName: "overseasPage"
    property bool advancedOpen: false
    property bool userDirty: false
    property bool loadingForm: false
    property bool awaitingReload: false
    property variant catalogItems: []
    property variant extraCarriers: []
    property variant preservedMeta: ({})
    property variant liveState: volteController.overseasState
    property string feedbackText: volteController.overseasFeedback
    function t(key) { var language = volteController.language; return volteController.label(key); }
    function usableApn(val) {
        if (!val) return "";
        var s = String(val).toLowerCase().replace(/^\s+|\s+$/g, "");
        if (s === "" || s === "other" || s === "unknown" || s === "auto") return "";
        return s;
    }
    function markDirty() {
        if (!loadingForm) userDirty = true;
    }
    function selectDropdownValue(dd, val) {
        for (var i = 0; i < dd.count(); ++i) {
            if (dd.at(i).value === val) {
                dd.setSelectedIndex(i);
                return;
            }
        }
    }
    function selectMatchingPreset(plmn) {
        if (!plmn || !catalogItems || !catalogItems.length) return;
        for (var i = 0; i < catalogItems.length; ++i) {
            if (catalogItems[i].plmn === plmn) {
                presetDrop.setSelectedIndex(i);
                return;
            }
        }
    }
    function resetAdvancedFields() {
        homeDomainField.text = "auto";
        alwaysOnCheck.checked = true;
        sigPcoCheck.checked = false;
        disableDadCheck.checked = false;
        selectDropdownValue(ueUsageDrop, "auto");
        selectDropdownValue(precondDrop, "");
        selectDropdownValue(smsFormatDrop, "");
    }
    function applyPreset(item, fromUser) {
        if (!item) return;
        loadingForm = true;
        extraCarriers = [];
        preservedMeta = {
            label: ((item.name ? String(item.name) : "") + " " + (item.plmn ? String(item.plmn) : "")).replace(/^\s+|\s+$/g, "")
        };
        mccField.text = item.mcc ? String(item.mcc) : "";
        mncField.text = item.mnc ? String(item.mnc) : "";
        var apns = ["auto"];
        var state = volteController.overseasState;
        var obs = state ? usableApn(state.observed_data_apn) : "";
        if (obs && apns.indexOf(obs) < 0) apns.push(obs);
        if (item.data_apns && item.data_apns.length) {
            for (var i = 0; i < item.data_apns.length; ++i) {
                if (apns.indexOf(item.data_apns[i]) < 0) apns.push(item.data_apns[i]);
            }
        }
        dataApnField.text = apns.join(", ");
        imsApnField.text = item.ims_apn ? String(item.ims_apn) : "ims";
        selectDropdownValue(ipFamilyDrop, item.ip_family ? String(item.ip_family) : "IPv4v6");
        smsCheck.checked = true;
        allowDefaultXmlCheck.checked = true;
        resetAdvancedFields();
        loadingForm = false;
        if (fromUser) userDirty = true;
    }
    function loadFromState(state) {
        if (!state) return;
        loadingForm = true;
        var cfg = state.config;
        var entry = null;
        extraCarriers = [];
        preservedMeta = {};
        if (cfg) {
            if (cfg.carriers && cfg.carriers.length > 0) {
                entry = cfg.carriers[0];
                var rest = [];
                for (var k = 1; k < cfg.carriers.length; ++k) rest.push(cfg.carriers[k]);
                extraCarriers = rest;
            } else {
                entry = cfg;
            }
        }
        if (entry) {
            mccField.text = entry.mcc ? String(entry.mcc) : "";
            mncField.text = entry.mncs ? entry.mncs.join(", ") : "";
            dataApnField.text = entry.data_apns ? entry.data_apns.join(", ") : "auto";
            var ims = entry.ims || {};
            imsApnField.text = ims.apn ? String(ims.apn) : "ims";
            selectDropdownValue(ipFamilyDrop, ims.ip_family ? String(ims.ip_family) : "IPv4v6");
            homeDomainField.text = ims.home_domain ? String(ims.home_domain) : "auto";
            smsCheck.checked = ims.sms !== false;
            allowIsimCheck.checked = entry.allow_isim === true;
            allowDefaultXmlCheck.checked = entry.allow_stock_default_xml !== false;
            alwaysOnCheck.checked = ims.always_on !== false;
            sigPcoCheck.checked = ims.request_signalling_bearer_via_pco === true;
            disableDadCheck.checked = ims.disable_dad === true;
            selectDropdownValue(ueUsageDrop, entry.ue_usage ? String(entry.ue_usage) : "auto");
            var ir92 = ims.ir92 || {};
            selectDropdownValue(precondDrop, ir92.UsePreconditions !== undefined ? String(ir92.UsePreconditions) : "");
            selectDropdownValue(smsFormatDrop, ir92.SMS_Format ? String(ir92.SMS_Format) : "");
            preservedMeta = {
                label: entry.label ? String(entry.label) : "",
                stock_config: entry.stock_config ? String(entry.stock_config) : "",
                amr_modeset_list: ir92.amr_modeset_list ? String(ir92.amr_modeset_list) : "",
                amrwb_modeset_list: ir92.amrwb_modeset_list ? String(ir92.amrwb_modeset_list) : "",
                ims_pps: ims.ims_pps || {}
            };
            loadingForm = false;
            selectMatchingPreset(state.sim_plmn);
            return;
        }
        mccField.text = "";
        mncField.text = "";
        dataApnField.text = "auto";
        imsApnField.text = "ims";
        selectDropdownValue(ipFamilyDrop, "IPv4v6");
        smsCheck.checked = true;
        allowIsimCheck.checked = state.sim_has_isim === true;
        allowDefaultXmlCheck.checked = true;
        resetAdvancedFields();
        loadingForm = false;
        if (state.matched_preset) {
            applyPreset(state.matched_preset, false);
        } else if (state.sim_plmn && String(state.sim_plmn).indexOf("-") > 0) {
            var parts = String(state.sim_plmn).split("-");
            if (parts[0] !== "460") {
                loadingForm = true;
                mccField.text = parts[0];
                mncField.text = parts[1];
                var obs = usableApn(state.observed_data_apn);
                dataApnField.text = obs ? ("auto, " + obs) : "auto";
                loadingForm = false;
            }
        }
        selectMatchingPreset(state.sim_plmn);
    }
    function refreshCatalog(query) {
        catalogItems = volteController.overseasCatalog(query || "");
        presetDrop.removeAll();
        for (var i = 0; i < catalogItems.length; ++i) {
            var item = catalogItems[i];
            var opt = optionDef.createObject();
            opt.text = item.plmn + " · " + item.name + (item.country ? (" (" + item.country + ")") : "");
            opt.value = i;
            presetDrop.add(opt);
        }
        if (catalogItems.length > 0) {
            presetDrop.setSelectedIndex(0);
            if (!query && volteController.overseasState && volteController.overseasState.sim_plmn)
                selectMatchingPreset(volteController.overseasState.sim_plmn);
        }
    }
    onFeedbackTextChanged: {
        if (feedbackText.length > 0 &&
            feedbackText !== t("overseas_saved_notice") &&
            feedbackText !== t("overseas_cleared_notice")) {
            awaitingReload = false;
        }
    }
    onLiveStateChanged: {
        if (!userDirty || awaitingReload) {
            awaitingReload = false;
            userDirty = false;
            loadFromState(liveState);
        }
    }
    titleBar: TitleBar { title: page.t("overseas_title") }
    onCreationCompleted: {
        refreshCatalog("");
        loadFromState(volteController.overseasState);
        volteController.inspectOverseasConfig();
    }
    ScrollView {
        scrollViewProperties.scrollMode: ScrollMode.Vertical
        Container {
            leftPadding: 24
            rightPadding: 24
            topPadding: 16
            bottomPadding: 32
            Label {
                text: page.t("overseas_note")
                multiline: true
                textStyle.fontSize: FontSize.Small
                textFormat: TextFormat.Plain
            }
            Label {
                text: volteController.overseasFeedback
                visible: text.length > 0
                multiline: true
                textStyle.fontWeight: FontWeight.W500
                textFormat: TextFormat.Plain
            }
            Label {
                text: volteController.statusTitle + (volteController.statusMessage.length > 0 ? ("\n" + volteController.statusMessage) : "")
                multiline: true
                textStyle.fontSize: FontSize.Small
                textFormat: TextFormat.Plain
            }
            Divider {}
            TextField {
                id: searchField
                hintText: page.t("overseas_search")
                onTextChanging: page.refreshCatalog(text)
            }
            DropDown {
                id: presetDrop
                title: page.t("overseas_preset")
                enabled: !volteController.busy
            }
            Button {
                text: page.t("overseas_apply_preset")
                horizontalAlignment: HorizontalAlignment.Fill
                enabled: !volteController.busy && page.catalogItems.length > 0 && presetDrop.selectedIndex >= 0
                onClicked: {
                    if (presetDrop.selectedIndex >= 0 && presetDrop.selectedIndex < page.catalogItems.length)
                        page.applyPreset(page.catalogItems[presetDrop.selectedIndex], true);
                }
            }
            Divider {}
            Label { text: page.t("overseas_mcc"); textStyle.fontSize: FontSize.Small }
            TextField { id: mccField; hintText: "450"; inputMode: TextFieldInputMode.NumbersAndPunctuation; onTextChanging: page.markDirty() }
            Label { text: page.t("overseas_mncs"); textStyle.fontSize: FontSize.Small }
            TextField { id: mncField; hintText: "08"; onTextChanging: page.markDirty() }
            Label { text: page.t("overseas_data_apns"); textStyle.fontSize: FontSize.Small }
            TextField { id: dataApnField; text: "auto"; hintText: "auto, lte.ktfwing.com"; onTextChanging: page.markDirty() }
            Label { text: page.t("overseas_ims_apn"); textStyle.fontSize: FontSize.Small }
            TextField { id: imsApnField; text: "ims"; hintText: "ims"; onTextChanging: page.markDirty() }
            DropDown {
                id: ipFamilyDrop
                title: page.t("overseas_ip_family")
                options: [
                    Option { text: "IPv4v6"; value: "IPv4v6"; selected: true },
                    Option { text: "IPv4"; value: "IPv4" },
                    Option { text: "IPv6"; value: "IPv6" }
                ]
                onSelectedOptionChanged: page.markDirty()
            }
            CheckBox { id: smsCheck; text: page.t("overseas_sms"); checked: true; onCheckedChanged: page.markDirty() }
            CheckBox { id: allowIsimCheck; text: page.t("overseas_allow_isim"); checked: false; onCheckedChanged: page.markDirty() }
            CheckBox { id: allowDefaultXmlCheck; text: page.t("overseas_allow_0xml"); checked: true; onCheckedChanged: page.markDirty() }
            Divider {}
            Button {
                text: page.t(page.advancedOpen ? "overseas_advanced_hide" : "overseas_advanced_show")
                horizontalAlignment: HorizontalAlignment.Fill
                onClicked: page.advancedOpen = !page.advancedOpen
            }
            Container {
                visible: page.advancedOpen
                topPadding: 8
                Label { text: page.t("overseas_home_domain"); textStyle.fontSize: FontSize.Small }
                TextField { id: homeDomainField; text: "auto"; onTextChanging: page.markDirty() }
                CheckBox { id: alwaysOnCheck; text: page.t("overseas_always_on"); checked: true; onCheckedChanged: page.markDirty() }
                CheckBox { id: sigPcoCheck; text: page.t("overseas_sig_pco"); checked: false; onCheckedChanged: page.markDirty() }
                CheckBox { id: disableDadCheck; text: page.t("overseas_disable_dad"); checked: false; onCheckedChanged: page.markDirty() }
                DropDown {
                    id: ueUsageDrop
                    title: page.t("overseas_ue_usage")
                    options: [
                        Option { text: page.t("overseas_ue_auto"); value: "auto"; selected: true },
                        Option { text: page.t("overseas_ue_voice"); value: "voice_centric" },
                        Option { text: page.t("overseas_ue_data"); value: "data_centric" }
                    ]
                    onSelectedOptionChanged: page.markDirty()
                }
                DropDown {
                    id: precondDrop
                    title: page.t("overseas_use_precond")
                    options: [
                        Option { text: page.t("overseas_unchanged"); value: ""; selected: true },
                        Option { text: "0"; value: "0" },
                        Option { text: "1"; value: "1" }
                    ]
                    onSelectedOptionChanged: page.markDirty()
                }
                DropDown {
                    id: smsFormatDrop
                    title: page.t("overseas_sms_format")
                    options: [
                        Option { text: page.t("overseas_unchanged"); value: ""; selected: true },
                        Option { text: "3GPP"; value: "3GPP" },
                        Option { text: "3GPP2"; value: "3GPP2" }
                    ]
                    onSelectedOptionChanged: page.markDirty()
                }
            }
            Divider {}
            Button {
                text: page.t("overseas_save")
                horizontalAlignment: HorizontalAlignment.Fill
                enabled: !volteController.busy && volteController.allowed("overseas-save")
                onClicked: {
                    page.awaitingReload = true;
                    var meta = page.preservedMeta || {};
                    volteController.saveOverseasConfig({
                        mcc: mccField.text,
                        mncs: mncField.text,
                        data_apns: dataApnField.text,
                        ims_apn: imsApnField.text,
                        ip_family: ipFamilyDrop.selectedOption ? ipFamilyDrop.selectedOption.value : "IPv4v6",
                        sms: smsCheck.checked,
                        allow_isim: allowIsimCheck.checked,
                        allow_stock_default_xml: allowDefaultXmlCheck.checked,
                        home_domain: homeDomainField.text,
                        always_on: alwaysOnCheck.checked,
                        request_signalling_bearer_via_pco: sigPcoCheck.checked,
                        disable_dad: disableDadCheck.checked,
                        ue_usage: ueUsageDrop.selectedOption ? ueUsageDrop.selectedOption.value : "auto",
                        use_preconditions: precondDrop.selectedOption ? precondDrop.selectedOption.value : "",
                        sms_format: smsFormatDrop.selectedOption ? smsFormatDrop.selectedOption.value : "",
                        label: meta.label || "",
                        stock_config: meta.stock_config || "",
                        amr_modeset_list: meta.amr_modeset_list || "",
                        amrwb_modeset_list: meta.amrwb_modeset_list || "",
                        ims_pps: meta.ims_pps || {},
                        extra_carriers: page.extraCarriers || []
                    });
                }
            }
            Button {
                text: page.t("overseas_clear")
                horizontalAlignment: HorizontalAlignment.Fill
                enabled: !volteController.busy && volteController.allowed("overseas-clear")
                onClicked: {
                    page.awaitingReload = true;
                    volteController.clearOverseasConfig();
                }
            }
        }
    }
    attachedObjects: [
        ComponentDefinition { id: optionDef; Option {} }
    ]
}
