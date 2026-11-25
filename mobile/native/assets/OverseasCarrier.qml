import bb.cascades 1.4

Page {
    id: page
    objectName: "overseasPage"
    property bool advancedOpen: false
    property bool userDirty: false
    property bool loadingForm: true
    property bool awaitingReload: false
    property variant catalogItems: []
    property int catalogTotal: 0
    property variant extraCarriers: []
    property variant preservedMeta: ({})
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
    function extraCarrierSummary() {
        if (!extraCarriers || !extraCarriers.length) return "";
        var list = [];
        for (var i = 0; i < extraCarriers.length; ++i) {
            var item = extraCarriers[i];
            if (item && item.mcc && item.mncs && item.mncs.length) {
                for (var j = 0; j < item.mncs.length; ++j)
                    list.push(String(item.mcc) + "-" + String(item.mncs[j]));
            }
        }
        return list.slice(0, 8).join(", ");
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
        var kept = [];
        if (extraCarriers && extraCarriers.length) {
            for (var k = 0; k < extraCarriers.length; ++k) {
                var ex = extraCarriers[k];
                if (!ex || ex.mcc !== item.mcc) {
                    kept.push(ex);
                } else if (ex.mncs && ex.mncs.length) {
                    var remain = [];
                    for (var m = 0; m < ex.mncs.length; ++m) {
                        if (String(ex.mncs[m]) !== String(item.mnc)) remain.push(ex.mncs[m]);
                    }
                    if (remain.length) {
                        var copy = {};
                        for (var prop in ex) copy[prop] = ex[prop];
                        copy.mncs = remain;
                        kept.push(copy);
                    }
                }
            }
        }
        extraCarriers = kept;
        preservedMeta = {
            label: ((item.name ? String(item.name) : "") + " " + (item.plmn ? String(item.plmn) : "")).replace(/^\s+|\s+$/g, "")
        };
        mccField.text = item.mcc ? String(item.mcc) : "";
        mncField.text = item.mnc ? String(item.mnc) : "";
        var apns = ["auto"];
        var state = volteController.overseasState;
        if (state && state.sim_plmn && String(state.sim_plmn) === String(item.plmn)) {
            var obs = usableApn(state.observed_data_apn);
            if (obs && apns.indexOf(obs) < 0) apns.push(obs);
        }
        if (item.data_apns && item.data_apns.length) {
            for (var i = 0; i < item.data_apns.length; ++i) {
                if (apns.indexOf(item.data_apns[i]) < 0) apns.push(item.data_apns[i]);
            }
        }
        dataApnField.text = apns.join(", ");
        imsApnField.text = item.ims_apn ? String(item.ims_apn) : "ims";
        selectDropdownValue(ipFamilyDrop, item.ip_family ? String(item.ip_family) : "IPv4v6");
        smsCheck.checked = true;
        if (!fromUser)
            allowIsimCheck.checked = Boolean(state && state.sim_plmn === item.plmn && state.sim_has_isim === true);
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
                var pickIdx = 0;
                if (state.sim_plmn && String(state.sim_plmn).indexOf("-") > 0) {
                    var sp = String(state.sim_plmn).split("-");
                    for (var c = 0; c < cfg.carriers.length; ++c) {
                        var cand = cfg.carriers[c];
                        if (cand && String(cand.mcc) === sp[0] && cand.mncs && cand.mncs.indexOf(sp[1]) >= 0) {
                            pickIdx = c;
                            break;
                        }
                    }
                }
                entry = cfg.carriers[pickIdx];
                var rest = [];
                for (var k = 0; k < cfg.carriers.length; ++k) {
                    if (k !== pickIdx) rest.push(cfg.carriers[k]);
                }
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
            if (ir92.UsePreconditions === undefined) {
                selectDropdownValue(precondDrop, "");
            } else {
                selectDropdownValue(precondDrop, (ir92.UsePreconditions === true || ir92.UsePreconditions === 1) ? "true" : "false");
            }
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
        var q = query || "";
        catalogItems = volteController.overseasCatalog(q);
        catalogTotal = volteController.overseasCatalogTotal(q);
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
            if (!q && volteController.overseasState && volteController.overseasState.sim_plmn)
                selectMatchingPreset(volteController.overseasState.sim_plmn);
        }
    }
    function handleOverseasFinished(action, ok, errorCode) {
        if (ok) {
            if (action !== "overseas-inspect" || !page.userDirty || page.awaitingReload) {
                page.awaitingReload = false;
                page.userDirty = false;
                page.loadFromState(volteController.overseasState);
            }
        } else {
            page.awaitingReload = false;
        }
    }
    titleBar: TitleBar { title: page.t("overseas_title") }
    onCreationCompleted: {
        loadingForm = true;
        volteController.overseasActionFinished.connect(page.handleOverseasFinished);
        refreshCatalog("");
        loadFromState(volteController.overseasState);
        userDirty = false;
        loadingForm = false;
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
            ActivityIndicator {
                running: volteController.busy
                visible: volteController.busy
                horizontalAlignment: HorizontalAlignment.Center
            }
            Label {
                text: volteController.overseasFeedback
                visible: text.length > 0
                multiline: true
                textStyle.fontWeight: FontWeight.W500
                textFormat: TextFormat.Plain
            }
            Label {
                text: page.t("overseas_extra_preserved") + page.extraCarrierSummary()
                visible: page.extraCarriers && page.extraCarriers.length > 0
                multiline: true
                textStyle.fontSize: FontSize.Small
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
                enabled: !volteController.busy
                hintText: page.t("overseas_search")
                input.flags: TextInputFlag.AutoCapitalizationOff | TextInputFlag.AutoCorrectionOff | TextInputFlag.SpellCheckOff | TextInputFlag.PredictionOff
                onTextChanging: page.refreshCatalog(text)
            }
            Label {
                text: page.t("overseas_more_matches")
                visible: page.catalogTotal > page.catalogItems.length
                multiline: true
                textStyle.fontSize: FontSize.XSmall
                textFormat: TextFormat.Plain
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
            TextField {
                id: mccField
                enabled: !volteController.busy
                hintText: "450"
                inputMode: TextFieldInputMode.NumbersAndPunctuation
                input.flags: TextInputFlag.AutoCapitalizationOff | TextInputFlag.AutoCorrectionOff | TextInputFlag.SpellCheckOff | TextInputFlag.PredictionOff
                onTextChanging: page.markDirty()
            }
            Label { text: page.t("overseas_mncs"); textStyle.fontSize: FontSize.Small }
            TextField {
                id: mncField
                enabled: !volteController.busy
                hintText: "08"
                inputMode: TextFieldInputMode.NumbersAndPunctuation
                input.flags: TextInputFlag.AutoCapitalizationOff | TextInputFlag.AutoCorrectionOff | TextInputFlag.SpellCheckOff | TextInputFlag.PredictionOff
                onTextChanging: page.markDirty()
            }
            Label { text: page.t("overseas_data_apns"); textStyle.fontSize: FontSize.Small }
            TextField {
                id: dataApnField
                enabled: !volteController.busy
                text: "auto"
                hintText: "auto, lte.ktfwing.com"
                input.flags: TextInputFlag.AutoCapitalizationOff | TextInputFlag.AutoCorrectionOff | TextInputFlag.SpellCheckOff | TextInputFlag.PredictionOff
                onTextChanging: page.markDirty()
            }
            Label { text: page.t("overseas_ims_apn"); textStyle.fontSize: FontSize.Small }
            TextField {
                id: imsApnField
                enabled: !volteController.busy
                text: "ims"
                hintText: "ims"
                input.flags: TextInputFlag.AutoCapitalizationOff | TextInputFlag.AutoCorrectionOff | TextInputFlag.SpellCheckOff | TextInputFlag.PredictionOff
                onTextChanging: page.markDirty()
            }
            DropDown {
                id: ipFamilyDrop
                enabled: !volteController.busy
                title: page.t("overseas_ip_family")
                options: [
                    Option { text: "IPv4v6"; value: "IPv4v6"; selected: true },
                    Option { text: "IPv4"; value: "IPv4" },
                    Option { text: "IPv6"; value: "IPv6" }
                ]
                onSelectedOptionChanged: page.markDirty()
            }
            CheckBox { id: smsCheck; enabled: !volteController.busy; text: page.t("overseas_sms"); checked: true; onCheckedChanged: page.markDirty() }
            CheckBox { id: allowIsimCheck; enabled: !volteController.busy; text: page.t("overseas_allow_isim"); checked: false; onCheckedChanged: page.markDirty() }
            CheckBox { id: allowDefaultXmlCheck; enabled: !volteController.busy; text: page.t("overseas_allow_0xml"); checked: true; onCheckedChanged: page.markDirty() }
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
                TextField {
                    id: homeDomainField
                    enabled: !volteController.busy
                    text: "auto"
                    input.flags: TextInputFlag.AutoCapitalizationOff | TextInputFlag.AutoCorrectionOff | TextInputFlag.SpellCheckOff | TextInputFlag.PredictionOff
                    onTextChanging: page.markDirty()
                }
                CheckBox { id: alwaysOnCheck; enabled: !volteController.busy; text: page.t("overseas_always_on"); checked: true; onCheckedChanged: page.markDirty() }
                CheckBox { id: sigPcoCheck; enabled: !volteController.busy; text: page.t("overseas_sig_pco"); checked: false; onCheckedChanged: page.markDirty() }
                CheckBox { id: disableDadCheck; enabled: !volteController.busy; text: page.t("overseas_disable_dad"); checked: false; onCheckedChanged: page.markDirty() }
                DropDown {
                    id: ueUsageDrop
                    enabled: !volteController.busy
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
                    enabled: !volteController.busy
                    title: page.t("overseas_use_precond")
                    options: [
                        Option { text: page.t("overseas_unchanged"); value: ""; selected: true },
                        Option { text: page.t("overseas_bool_false"); value: "false" },
                        Option { text: page.t("overseas_bool_true"); value: "true" }
                    ]
                    onSelectedOptionChanged: page.markDirty()
                }
                DropDown {
                    id: smsFormatDrop
                    enabled: !volteController.busy
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
