# -*- coding: utf-8 -*-

from xml.dom import minidom, Node


def disable_urllib3_warning():
    """
    https://urllib3.readthedocs.org/en/latest/security.html#insecurerequestwarning
    InsecurePlatformWarning 警告的临时解决方案
    """
    try:
        import requests.packages.urllib3
        requests.packages.urllib3.disable_warnings()
    except Exception:
        pass


class XMLStore(object):
    """
    XML 存储类，可方便转换为 Dict
    """
    def __init__(self, xmlstring):
        self._raw = xmlstring
        self._doc = minidom.parseString(xmlstring)

    @property
    def xml2dict(self):
        """
        将 XML 转换为 dict
        """
        self._remove_whitespace_nodes(self._doc.childNodes[0])
        return self._element2dict(self._doc.childNodes[0])

    def _element2dict(self, parent):
        """
        将单个节点转换为 dict
        """
        d = {}
        for node in parent.childNodes:
            if not isinstance(node, minidom.Element):
                continue
            if not node.hasChildNodes():
                continue

            if node.childNodes[0].nodeType == minidom.Node.ELEMENT_NODE:
                try:
                    d[node.tagName]
                except KeyError:
                    d[node.tagName] = []
                d[node.tagName].append(self._element2dict(node))
            elif len(node.childNodes) == 1 and node.childNodes[0].nodeType in [minidom.Node.CDATA_SECTION_NODE, minidom.Node.TEXT_NODE]:
                d[node.tagName] = node.childNodes[0].data
        return d

    def _remove_whitespace_nodes(self, node, unlink=True):
        """
        删除空白无用节点
        """
        remove_list = []
        for child in node.childNodes:
            if child.nodeType == Node.TEXT_NODE and not child.data.strip():
                remove_list.append(child)
            elif child.hasChildNodes():
                self._remove_whitespace_nodes(child, unlink)
        for node in remove_list:
            node.parentNode.removeChild(node)
            if unlink:
                node.unlink()


def dict2xml(_dict):
    xml_el_tpl = "<{tag}>{value}</{tag}>"
    el_list = []

    sorted_keys = sorted(_dict.keys())

    for key in sorted_keys:
        value = _dict.get(key)

        if isinstance(value, (int, float, bool)):
            value = str(value)

        if type(value) == unicode:
            value = value.encode('utf-8')
        elif type(value) == str:
            value = value.decode('utf-8').encode('utf-8')
        else:
            raise ValueError("not support type: %s" % type(value))

        el_list.append(xml_el_tpl.format(tag=key, value=value))

    return "<xml>\n" + "\n".join(el_list) + "\n</xml>"


def xml2dict(xml_str):
    xml = XMLStore(xml_str)

    return xml.xml2dict

