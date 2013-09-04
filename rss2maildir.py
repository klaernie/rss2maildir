#!/usr/bin/python
# coding=utf-8

# rss2maildir.py - RSS feeds to Maildir 1 email per item
# Copyright (C) 2007  Brett Parker <iDunno@sommitrealweird.co.uk>
# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import sys
import os
import stat
import httplib
import urllib

import feedparser
from lxml import html

from email.MIMEMultipart import MIMEMultipart
from email.MIMEText import MIMEText
from email.header import Header

import datetime
import random
import string
import textwrap

import socket

from optparse import OptionParser
from ConfigParser import SafeConfigParser

from base64 import b64encode

import chardet

if sys.version_info[0] == 2 and sys.version_info[1] >= 6:
    import hashlib as md5
else:
    import md5

import cgi
import dbm

import re

def open_url(method, url):
    redirectcount = 0
    while redirectcount < 3:
        (type, rest) = urllib.splittype(url)
        (host, path) = urllib.splithost(rest)
        (host, port) = urllib.splitport(host)
        if type == "https":
            if port == None:
                port = 443
        elif port == None:
            port = 80
        try:
            conn = None
            if type == "http":
                conn = httplib.HTTPConnection("%s:%s" %(host, port))
            else:
                conn = httplib.HTTPSConnection("%s:%s" %(host, port))
            conn.request(method, path)
            response = conn.getresponse()
            if response.status in [301, 302, 303, 307]:
                headers = response.getheaders()
                for header in headers:
                    if header[0] == "location":
                        url = header[1]
            elif response.status == 200:
                return response
        except:
            pass
        redirectcount = redirectcount + 1
    return None

def parse_and_deliver(maildir, url, statedir):
    feedhandle = None
    headers = None
    # first check if we know about this feed already
    feeddb = dbm.open(os.path.join(statedir, "feeds"), "c")
    if feeddb.has_key(url):
        data = feeddb[url]
        data = cgi.parse_qs(data)
        response = open_url("HEAD", url)
        headers = None
        if response:
            headers = response.getheaders()
        ischanged = False
        try:
            for header in headers:
                if header[0] == "content-length":
                    if header[1] != data["content-length"][0]:
                        ischanged = True
                elif header[0] == "etag":
                    if header[1] != data["etag"][0]:
                        ischanged = True
                elif header[0] == "last-modified":
                    if header[1] != data["last-modified"][0]:
                        ischanged = True
                elif header[0] == "content-md5":
                    if header[1] != data["content-md5"][0]:
                        ischanged = True
        except:
            ischanged = True
        if ischanged:
            response = open_url("GET", url)
            if response != None:
                headers = response.getheaders()
                feedhandle = response
            else:
                sys.stderr.write("Failed to fetch feed: %s\n" %(url))
                return
        else:
            return # don't need to do anything, nothings changed.
    else:
        response = open_url("GET", url)
        if response != None:
            headers = response.getheaders()
            feedhandle = response
        else:
            sys.stderr.write("Failed to fetch feed: %s\n" %(url))
            return

    fp = feedparser.parse(feedhandle)
    db = dbm.open(os.path.join(statedir, "seen"), "c")
    for item in fp["items"]:
        # have we seen it before?
        # need to work out what the content is first...

        if item.has_key("content"):
            content = item["content"][0]["value"]
        else:
            if item.has_key("description"):
                content = item["description"]
            else:
                content = u''

        md5sum = md5.md5(content.encode("utf-8")).hexdigest()

        # make sure content is unicode encoded
        if not isinstance(content, unicode):
            cd_res = chardet.detect(content)
            chrset = cd_res['encoding']
            print "detected charset %s for item %s" %(chrset, item["link"])
            content = content.decode(chrset)

        prevmessageid = None

        db_guid_key = None
        db_link_key = (url + u'|' + item["link"]).encode("utf-8")

        # check if there's a guid too - if that exists and we match the md5,
        # return
        if item.has_key("guid"):
            db_guid_key = (url + u'|' + item["guid"]).encode("utf-8")
            if db.has_key(db_guid_key):
                data = db[db_guid_key]
                data = cgi.parse_qs(data)
                if data["contentmd5"][0] == md5sum:
                    continue

        if db.has_key(db_link_key):
            data = db[db_link_key]
            data = cgi.parse_qs(data)
            if data.has_key("message-id"):
                prevmessageid = data["message-id"][0]
            if data["contentmd5"][0] == md5sum:
                continue

        try:
            author = item["author"]
        except:
            author = url

        # create a basic email message
        msg = MIMEMultipart("alternative")
        messageid = "<" \
            + datetime.datetime.now().strftime("%Y%m%d%H%M") \
            + "." \
            + "".join( \
                [random.choice( \
                    string.ascii_letters + string.digits \
                    ) for a in range(0,6) \
                ]) + "@" + socket.gethostname() + ">"
        msg.add_header("Message-ID", messageid)
        msg.set_unixfrom("\"%s\" <rss2maildir@localhost>" %(url))
        msg.add_header("From", "\"%s\" <rss2maildir@localhost>" %(author.encode("utf-8")))
        msg.add_header("To", "\"%s\" <rss2maildir@localhost>" %(url.encode("utf-8")))
        if prevmessageid:
            msg.add_header("References", prevmessageid)
        createddate = datetime.datetime.now() \
            .strftime("%a, %e %b %Y %T -0000")
        try:
            createddate = datetime.datetime(*item["updated_parsed"][0:6]) \
                .strftime("%a, %e %b %Y %T -0000")
        except:
            pass
        msg.add_header("Date", createddate)
        msg.add_header("X-rss2maildir-rundate", datetime.datetime.now() \
            .strftime("%a, %e %b %Y %T -0000"))
        title = html.fromstring(item["title"]).text
        title = re.sub(u'<', u'&lt;', title)
        title = re.sub(u'>', u'&gt;', title)
        msg.add_header("Subject", str(Header(title.encode("utf-8"),"utf-8")))
        msg.set_default_type("text/plain")

        htmlcontent = content.encode("utf-8")
        htmlcontent = "%s\n\n<p>Item URL: <a href='%s'>%s</a></p>" %( \
            content, \
            item["link"], \
            item["link"] )
        htmlpart = MIMEText(htmlcontent.encode("utf-8"), "html", "utf-8")
        msg.attach(htmlpart)

        # start by working out the filename we should be writting to, we do
        # this following the normal maildir style rules
        fname = str(os.getpid()) \
            + "." + socket.gethostname() \
            + "." + "".join( \
                [random.choice( \
                    string.ascii_letters + string.digits \
                    ) for a in range(0,10) \
                ]) + "." \
            + datetime.datetime.now().strftime('%s')
        fn = os.path.join(maildir, "tmp", fname)
        fh = open(fn, "w")
        fh.write(msg.as_string())
        fh.close()
        # now move it in to the new directory
        newfn = os.path.join(maildir, "new", fname)
        os.link(fn, newfn)
        os.unlink(fn)

        # now add to the database about the item
        if prevmessageid:
            messageid = prevmessageid + " " + messageid
        if item.has_key("guid") and item["guid"] != item["link"]:
            data = urllib.urlencode(( \
                ("message-id", messageid), \
                ("created", createddate), \
                ("contentmd5", md5sum) \
                ))
            db[db_guid_key] = data
            try:
                data = db[db_link_key]
                data = cgi.parse_qs(data)
                newdata = urllib.urlencode(( \
                    ("message-id", messageid), \
                    ("created", data["created"][0]), \
                    ("contentmd5", data["contentmd5"][0]) \
                    ))
                db[db_link_key] = newdata
            except:
                db[db_link_key] = data
        else:
            data = urllib.urlencode(( \
                ("message-id", messageid), \
                ("created", createddate), \
                ("contentmd5", md5sum) \
                ))
            db[db_link_key] = data

    if headers:
        data = []
        for header in headers:
            if header[0] in \
                ["content-md5", "etag", "last-modified", "content-length"]:
                data.append((header[0], header[1]))
        if len(data) > 0:
            data = urllib.urlencode(data)
            feeddb[url] = data

    db.close()
    feeddb.close()

if __name__ == "__main__":
    # This only gets executed if we really called the program
    # first off, parse the command line arguments

    oparser = OptionParser()
    oparser.add_option(
        "-c", "--conf", dest="conf",
        help="location of config file"
        )
    oparser.add_option(
        "-s", "--statedir", dest="statedir",
        help="location of directory to store state in"
        )

    (options, args) = oparser.parse_args()

    # check for the configfile

    configfile = None

    if options.conf != None:
        # does the file exist?
        try:
            os.stat(options.conf)
            configfile = options.conf
        except:
            # should exit here as the specified file doesn't exist
            sys.stderr.write( \
                "Config file %s does not exist. Exiting.\n" %(options.conf,))
            sys.exit(2)
    else:
        # check through the default locations
        try:
            os.stat("%s/.rss2maildir.conf" %(os.environ["HOME"],))
            configfile = "%s/.rss2maildir.conf" %(os.environ["HOME"],)
        except:
            try:
                os.stat("/etc/rss2maildir.conf")
                configfile = "/etc/rss2maildir.conf"
            except:
                sys.stderr.write("No config file found. Exiting.\n")
                sys.exit(2)

    # Right - if we've got this far, we've got a config file, now for the hard
    # bits...

    scp = SafeConfigParser()
    scp.read(configfile)

    maildir_root = "RSSMaildir"
    state_dir = "state"

    if options.statedir != None:
        state_dir = options.statedir
        try:
            mode = os.stat(state_dir)[stat.ST_MODE]
            if not stat.S_ISDIR(mode):
                sys.stderr.write( \
                    "State directory (%s) is not a directory\n" %(state_dir))
                sys.exit(1)
        except:
            # try to make the directory
            try:
                os.mkdir(state_dir)
            except:
                sys.stderr.write("Couldn't create statedir %s" %(state_dir))
                sys.exit(1)
    elif scp.has_option("general", "state_dir"):
        new_state_dir = scp.get("general", "state_dir")
        try:
            mode = os.stat(new_state_dir)[stat.ST_MODE]
            if not stat.S_ISDIR(mode):
                sys.stderr.write( \
                    "State directory (%s) is not a directory\n" %(state_dir))
                sys.exit(1)
            else:
                state_dir = new_state_dir
        except:
            # try to create it
            try:
                os.mkdir(new_state_dir)
                state_dir = new_state_dir
            except:
                sys.stderr.write( \
                    "Couldn't create state directory %s\n" %(new_state_dir))
                sys.exit(1)
    else:
        try:
            mode = os.stat(state_dir)[stat.ST_MODE]
            if not stat.S_ISDIR(mode):
                sys.stderr.write( \
                    "State directory %s is not a directory\n" %(state_dir))
                sys.exit(1)
        except:
            try:
                os.mkdir(state_dir)
            except:
                sys.stderr.write( \
                    "State directory %s could not be created\n" %(state_dir))
                sys.exit(1)

    if scp.has_option("general", "maildir_root"):
        maildir_root = scp.get("general", "maildir_root")

    try:
        mode = os.stat(maildir_root)[stat.ST_MODE]
        if not stat.S_ISDIR(mode):
            sys.stderr.write( \
                "Maildir Root %s is not a directory\n" \
                %(maildir_root))
            sys.exit(1)
    except:
        try:
            os.mkdir(maildir_root)
        except:
            sys.stderr.write("Couldn't create Maildir Root %s\n" \
                %(maildir_root))
            sys.exit(1)

    feeds = scp.sections()
    try:
        feeds.remove("general")
    except:
        pass

    for section in feeds:
        # check if the directory exists
        maildir = None
        try:
            maildir = scp.get(section, "maildir")
        except:
            maildir = section

        maildir = urllib.urlencode(((section, maildir),)).split("=")[1]
        maildir = os.path.join(maildir_root, maildir)

        try:
            exists = os.stat(maildir)
            if stat.S_ISDIR(exists[stat.ST_MODE]):
                # check if there's a new, cur and tmp directory
                try:
                    mode = os.stat(os.path.join(maildir, "cur"))[stat.ST_MODE]
                except:
                    os.mkdir(os.path.join(maildir, "cur"))
                    if not stat.S_ISDIR(mode):
                        sys.stderr.write("Broken maildir: %s\n" %(maildir))
                try:
                    mode = os.stat(os.path.join(maildir, "tmp"))[stat.ST_MODE]
                except:
                    os.mkdir(os.path.join(maildir, "tmp"))
                    if not stat.S_ISDIR(mode):
                        sys.stderr.write("Broken maildir: %s\n" %(maildir))
                try:
                    mode = os.stat(os.path.join(maildir, "new"))[stat.ST_MODE]
                    if not stat.S_ISDIR(mode):
                        sys.stderr.write("Broken maildir: %s\n" %(maildir))
                except:
                    os.mkdir(os.path.join(maildir, "new"))
            else:
                sys.stderr.write("Broken maildir: %s\n" %(maildir))
        except:
            try:
                os.mkdir(maildir)
            except:
                sys.stderr.write("Couldn't create root maildir %s\n" \
                    %(maildir))
                sys.exit(1)
            try:
                os.mkdir(os.path.join(maildir, "new"))
                os.mkdir(os.path.join(maildir, "cur"))
                os.mkdir(os.path.join(maildir, "tmp"))
            except:
                sys.stderr.write( \
                    "Couldn't create required maildir directories for %s\n" \
                    %(section,))
                sys.exit(1)

        # right - we've got the directories, we've got the section, we know the
        # url... lets play!

        parse_and_deliver(maildir, section, state_dir)
