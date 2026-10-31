"""Read-only carrier selection/content cross-check; exports no identities."""
import json
import xml.etree.ElementTree as ET
import q20_volte_phone as q


def main():
    q.setup()
    q.verify()
    selected = q.n.value(q.n.attrs(q.n.read(q.s.CDSC)), 'cdsc_xml')
    assert selected == q.s.APN
    root = ET.fromstring(q.n.read(selected))
    for node in root.iter():
        node.tag = node.tag.rsplit('}', 1)[-1]
    ims = [node for node in root.iter('ServiceConfiguration') if node.findtext('Name') == 'ims']
    assert len(ims) == 1
    fields = ('AlwaysOn', 'NetworkInterfaceConfiguration/IPConfiguration/Type',
              'NetworkInterfaceConfiguration/IPConfiguration/DisableDAD',
              'IMSConfiguration/RequestPCSCFViaPCO', 'IMSConfiguration/RequestSignallingBearerViaPCO')
    print(json.dumps({'variant': 'SQC100-2', 'configured_profile': q.s.ACTIVE_PROFILE['id'],
        'selected_path': selected, 'matches_owned_runtime': selected == q.s.APN,
        'xml_sha256': q.n.digest(q.n.read(selected)),
        'carrier_id': root.findtext('.//CarrierID'),
        'internet_apns': sorted(set(node.text for entry in root.iter('ServiceConfiguration')
            if entry.findtext('Name') == 'internet' for node in entry.iter('APN'))),
        'ims': {field: ims[0].findtext(field) for field in fields},
        'registered': q.status()['registered'], 'configuration_writes': 0}))


if __name__ == '__main__':
    main()
