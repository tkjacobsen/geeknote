#!/usr/bin/env python2
# -*- coding: utf-8 -*-

import os
import argparse
import binascii
import logging
import re

import evernote.edam.type.ttypes as Types
from evernote.edam.limits.constants import EDAM_USER_NOTES_MAX
from bs4 import BeautifulSoup

import config
from geeknote import GeekNote
from storage import Storage
from editor import Editor
import tools


# set default logger (write log to file)
def_logpath = os.path.join(config.APP_DIR, 'gnbackup.log')
formatter = logging.Formatter('%(asctime)-15s : %(message)s')
handler = logging.FileHandler(def_logpath)
handler.setFormatter(formatter)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.addHandler(handler)

# http://en.wikipedia.org/wiki/Unicode_control_characters
CONTROL_CHARS_RE = re.compile(u'[\x00-\x08\x0e-\x1f\x7f-\x9f]')


def remove_control_characters(s):
    return CONTROL_CHARS_RE.sub('', s)


def log(func):
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception, e:
            logger.error("%s", str(e))
    return wrapper


@log
def reset_logpath(logpath):
    """
    Reset logpath to path from command line
    """
    global logger

    if not logpath:
        return

    # remove temporary log file if it's empty
    if os.path.isfile(def_logpath):
        if os.path.getsize(def_logpath) == 0:
            os.remove(def_logpath)

    # save previous handlers
    handlers = logger.handlers

    # remove old handlers
    for handler in handlers:
        logger.removeHandler(handler)

    # try to set new file handler
    handler = logging.FileHandler(logpath)
    handler.setFormatter(formatter)
    logger.addHandler(handler)

def all_notebooks():
    geeknote = GeekNote()
    return [notebook.name for notebook in geeknote.findNotebooks()]

class GNBackup:

    notebook_name = None
    path = None
    delete = None

    notebook_guid = None
    all_set = False

    @log
    def __init__(self, notebook_name, path, format, delete, imageOptions={'saveImages': False, 'imagesInSubdir': False}):
        # check auth
        if not Storage().getUserToken():
            raise Exception("Auth error. There is not any oAuthToken.")

        # set path
        if not path:
            raise Exception("Path to backup directory not defined.")

        self.path = path

        # set format
        if not format:
            format = "plain"

        self.format = format

        if format == "markdown":
            self.extension = ".md"
        elif format == "html":
            self.extension = ".html"
        else:
            self.extension = ".txt"

        self.delete = delete

        logger.info('Backup Start')

        # set notebook
        self.notebook_guid,\
            self.notebook_name = self._get_notebook(notebook_name, path)

        # set image options
        self.imageOptions = imageOptions

        # all is Ok
        self.all_set = True

    @log
    def backup(self):
        """
        Backup notes to files and delete extraneous files
        """
        if not self.all_set:
            return

        files = self._get_files()
        notes = self._get_notes()

        for n in notes:
            for f in files:
                if f['name'] == n.title:
                    if f['mtime'] < n.updated:
                        self._update_file(f, n)
                        break
            else:
                self._create_file(n)

        if self.delete:
            for f in files:
                for n in notes:
                    if f['name'] == n.title:
                        break
                else:
                    os.remove(f['path'])
                
        logger.info('Backup Complete')

    @log
    def _update_file(self, file_note, note):
        """
        Updates file from note
        """
        GeekNote().loadNoteContent(note)
        content = Editor.ENMLtoText(note.content)
        open(file_note['path'], "w").write(content)
        os.utime(file_note['path'], (-1, note.updated / 1000))

    @log
    def _create_file(self, note):
        """
        Creates file from note
        """
        GeekNote().loadNoteContent(note)

        # Save images
        if 'saveImages' in self.imageOptions and self.imageOptions['saveImages']:
            imageList = Editor.getImages(note.content)
            if imageList:
                if 'imagesInSubdir' in self.imageOptions and self.imageOptions['imagesInSubdir']:
                    os.mkdir(os.path.join(self.path, note.title + "_images"))
                    imagePath = os.path.join(self.path, note.title + "_images", note.title)
                    self.imageOptions['baseFilename'] = note.title + "_images/" + note.title
                else:
                    imagePath = os.path.join(self.path, note.title)
                    self.imageOptions['baseFilename'] = note.title
                for imageInfo in imageList:
                    filename = "{}-{}.{}".format(imagePath, imageInfo['hash'], imageInfo['extension'])
                    logger.info('Saving image to {}'.format(filename))
                    binaryHash = binascii.unhexlify(imageInfo['hash'])
                    GeekNote().saveMedia(note.guid, binaryHash, filename)

        content = Editor.ENMLtoText(note.content, self.imageOptions)
        path = os.path.join(self.path, note.title + self.extension)
        open(path, "w").write(content)
        os.utime(path, (-1, note.updated / 1000))

        return True

    @log
    def _get_notebook(self, notebook_name, path):
        """
        Get notebook guid and name.
        Takes default notebook if notebook's name does not select.
        """
        notebooks = GeekNote().findNotebooks()

        if not notebook_name:
            notebook_name = os.path.basename(os.path.realpath(path))

        notebook = [item for item in notebooks if item.name == notebook_name]
        guid = None
        if notebook:
            guid = notebook[0].guid

        if not guid:
            raise Exception('Notebook "{0}" does not exist'.format(notebook_name))

        return (guid, notebook_name)

    @log
    def _get_files(self):
        """
        Get files from self.path dir.
        """

        file_paths =  [os.path.join(self.path, f) for f in os.listdir(self.path) if os.path.isfile(os.path.join(self.path, f))]

        files = []
        for f in file_paths:
            if os.path.isfile(f):
                file_name = os.path.basename(f)
                file_name = os.path.splitext(file_name)[0]

                mtime = int(os.path.getmtime(f) * 1000)

                files.append({'path': f, 'name': file_name, 'mtime': mtime})

        return files

    @log
    def _get_notes(self):
        """
        Get notes from evernote.
        """
        keywords = 'notebook:"{0}"'.format(tools.strip(self.notebook_name))
        return GeekNote().findNotes(keywords, EDAM_USER_NOTES_MAX).notes


def main():
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument('--path', '-p', action='store', help='Path to backup directory')
        parser.add_argument('--format', '-f', action='store', default='plain', choices=['plain', 'markdown', 'html'], help='The format of the file contents. Default is "plain". Valid values are "plain" "html" and "markdown"')
        parser.add_argument('--notebook', '-n', action='store', help='Notebook to backun. Default is default notebook unless all is selected')
        parser.add_argument('--all', '-a', action='store_true', help='Backup all notebooks', default=False)
        parser.add_argument('--delete', action='store_true', help='Delete extraneous files from backup directory', default=False)
        parser.add_argument('--logpath', '-l', action='store', help='Path to log file. Default is GeekNoteSync in home dir')
        parser.add_argument('--save-images', action='store_true', help='save images along with text')
        parser.add_argument('--images-in-subdir', action='store_true', help='save images in a subdirectory (instead of same directory as file)')

        args = parser.parse_args()

        path = args.path if args.path else None
        format = args.format if args.format else None
        delete = args.delete if args.delete else None
        notebook = args.notebook if args.notebook else None
        logpath = args.logpath if args.logpath else None

        # image options
        imageOptions = {}
        imageOptions['saveImages'] = args.save_images
        imageOptions['imagesInSubdir'] = args.images_in_subdir

        reset_logpath(logpath)

        if not os.path.exists(path):
            os.mkdir(path)

        if args.all:
            for notebook in all_notebooks():
                logger.info("Backing up notebook %s", notebook)
                notebook_path = os.path.join(path, notebook)
                if not os.path.exists(notebook_path):
                    os.mkdir(notebook_path)
                GNS = GNBackup(notebook, notebook_path, format, delete, imageOptions)
                GNS.backup()
        else:
            GNS = GNBackup(notebook, path, format, delete, imageOptions)
            GNS.backup()

    except (KeyboardInterrupt, SystemExit, tools.ExitException):
        pass

    except Exception, e:
        logger.error(str(e))

if __name__ == "__main__":
    main()
