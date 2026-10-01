"""Adapt the upstream legacy source layout for the overlay's separated test tree."""
import argparse
from pathlib import Path
import xml.etree.ElementTree as ET

NS = 'http://maven.apache.org/POM/4.0.0'
ET.register_namespace('', NS)


def configure(root):
    path = Path(root) / 'Mage.Server.Plugins/Mage.Player.AI/pom.xml'
    tree = ET.parse(path)
    project = tree.getroot()
    def child(parent, name, text=None):
        element = parent.find('{%s}%s' % (NS, name))
        if element is None:
            element = ET.SubElement(parent, '{%s}%s' % (NS, name))
        if text is not None:
            element.text = text
        return element
    if child(project, 'artifactId').text != 'mage-player-ai':
        raise ValueError('Unexpected reference module; refusing to edit it.')
    build = child(project, 'build')
    child(build, 'testSourceDirectory', 'src/test/java')
    plugins = child(build, 'plugins')
    def plugin(artifact, version):
        for existing in plugins:
            if existing.findtext('{%s}artifactId' % NS) == artifact:
                plugins.remove(existing)
        result = ET.SubElement(plugins, '{%s}plugin' % NS)
        child(result, 'groupId', 'org.apache.maven.plugins')
        child(result, 'artifactId', artifact)
        child(result, 'version', version)
        return result
    compiler = plugin('maven-compiler-plugin', '3.13.0')
    excludes = child(child(compiler, 'configuration'), 'excludes')
    child(excludes, 'exclude', 'test/**')
    plugin('maven-surefire-plugin', '3.5.0')
    dependencies = child(project, 'dependencies')
    for group, artifact, version in (
        ('org.junit.jupiter', 'junit-jupiter', '5.11.0'),
        ('org.junit.vintage', 'junit-vintage-engine', '5.11.0'),
        ('org.assertj', 'assertj-core', '3.26.3'),
    ):
        if not any(d.findtext('{%s}artifactId' % NS) == artifact for d in dependencies):
            dep = ET.SubElement(dependencies, '{%s}dependency' % NS)
            for name, value in (('groupId', group), ('artifactId', artifact), ('version', version), ('scope', 'test')):
                child(dep, name, value)
    tree.write(path, encoding='utf-8', xml_declaration=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkout', type=Path)
    configure(parser.parse_args().checkout)
