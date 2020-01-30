#!/usr/bin/env python

import logging, subprocess

logger = logging.getLogger(__name__)

def get_fonts(folder=None):
    """
    Scan a folder (or the system) for .ttf / .otf fonts and
    return a dictionary of the structure  family -> style -> file path
    """
    fonts = {}
    if folder:
        cmd = ['fc-scan', '--format', '%{file}:%{family}:style=%{style}\n', folder]
    else:
        cmd = ['fc-list', ':', 'file', 'family', 'style']
    for line in subprocess.check_output(cmd).decode('utf-8').split("\n"):
        logger.debug(line)
        line.strip()
        if not line: continue
        if 'otf' not in line and 'ttf' not in line: continue
        parts = line.split(':')
        if 'style=' not in line or len(parts) < 3:
            # fc-list didn't output all desired properties
            logger.warn('skipping invalid font %s', line)
            continue
        path = parts[0]
        families = parts[1].strip().split(',')
        styles = parts[2].split('=')[1].split(',')
        if len(families) == 1 and len(styles) > 1:
            families = [families[0]] * len(styles)
        elif len(families) > 1 and len(styles) == 1:
            styles = [styles[0]] * len(families)
        if len(families) != len(styles):
            logger.debug("Problem with this font: " + line)
            continue
        for i in range(len(families)):
            try: fonts[families[i]]
            except: fonts[families[i]] = dict()
            fonts[families[i]][styles[i]] = path
            logger.debug("Added this font: " + str((families[i], styles[i], path)))
    return fonts
