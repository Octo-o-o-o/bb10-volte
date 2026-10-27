# Operator data research (2026-10-27)

[简体中文](CARRIER-RESEARCH.md)

This research did not find a complete, hardware-validated database covering all provinces, carriers, BB10 models and SIM types. Traceable APN samples and IMS standards are available; they cannot replace the actual SIM, network provisioning or device checks.

| Carrier | MCC / MNC in the snapshot | Data APN | IMS APN / family |
|---|---|---|---|
| Unicom | 460 / 01, 09 | 3gnet | ims / IPv4v6 |
| Mobile | 460 / 00, 02, 07 | cmnet | ims / IPv4v6 |
| Telecom | 460 / 03, 11 | ctnet | ims / IPv4v6 |

Facts were extracted from a [pinned AOSP commit](https://android.googlesource.com/device/sample/+/73f904fbeb872f5675cb5f18cd9dfb15856425a6/etc/apns-full-conf.xml). The upstream [README calls this a sample](https://android.googlesource.com/device/sample/+/main/etc/README), not BB10 certification. No 460-06 entry was returned by this query, so it was not added automatically. This is not a complete current MNC directory. See [provenance](../materials/carrier-data-sources.json) for the commit, original XML hash and selected facts; the full upstream XML is not redistributed.

[ETSI TS 23.003, sections 13.2–13.3](https://www.etsi.org/deliver/etsi_ts/123000_123099/123003/16.11.01_60/ts_123003v161101p.pdf) specifies identity/domain derivation without ISIM, using a three-digit MNC. The implementation uses the actual SIM rather than a profile's first MNC.

[ETSI TS 31.103](https://www.etsi.org/deliver/etsi_ts/131100_131199/131103/14.04.00_60/ts_131103v140400p.pdf) defines ISIM files for IMPI, domain, IMPU and P-CSCF. ISIM cards need a dedicated implementation. Subscriber identities, authentication, current P-CSCF, subscription provisioning and terminal policies cannot come from a universal APN list.

Official [Unicom](https://img.client.10010.com/stprototype/volte/volte.html) and [Telecom](https://www.189.cn/volte/) guidance also requires suitable terminals/services. Those pages do not publish a complete recipe for arbitrary BB10 phones. A template, passing preflight or registration alone does not establish usable calls.

The tool starts with the phone's stock home-carrier selection and replaces only its IMS section, checking the data APN first. This prevents silently reusing Unicom's stock data configuration for another carrier. P-CSCF is obtained from network PCO. Testers supply home/current province, porting/roaming context and real-call acceptance. Sanitized success/failure reports and PRs can build a traceable compatibility record over time.
