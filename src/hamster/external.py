# - coding: utf-8 -

# Copyright (C) 2007 Patryk Zawadzki <patrys at pld-linux.org>
# Copyright (C) 2008, 2010 Toms Bauģis <toms.baugis at gmail.com>

# This file is part of Project Hamster.

# Project Hamster is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# Project Hamster is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with Project Hamster.  If not, see <http://www.gnu.org/licenses/>.

import gtk
import os
import logging
# from configuration import conf
import re
import dbus.mainloop.glib
import json
from lib import rt
from lib import redmine
from lib.rt import DEFAULT_RT_CATEGORY
from beaker.cache import cache_regions, cache_region

jira_active = True
try:
    from jira.client import JIRA
except ImportError:
    JIRA = None
    jira_active = False

try:
    import configparser
except ImportError:
    from six.moves import configparser

try:
    import evolution
    from evolution import ecal
except ImportError:
    ecal = None
    evolution = None

# configure regions
cache_regions.update({
    'short_term': {
        'expire': 60 * 1000,
        'type': 'memory',
        'key_length': 250
    }
})
logger = logging.getLogger("external")

SOURCE_NONE = ""
SOURCE_GTG = 'gtg'
SOURCE_EVOLUTION = 'evo'
SOURCE_RT = 'rt'
SOURCE_REDMINE = 'redmine'
SOURCE_JIRA = 'jira'
JIRA_ISSUE_NAME_REGEX = "^(\w+-\d+): "
ERROR_ADDITIONAL_MESSAGE = '\n\nCheck settings and reopen main window.'
MIN_QUERY_LENGTH = 3
CURRENT_USER_ACTIVITIES_LIMIT = 5


class ActivitiesSource(object):
    def __init__(self, conf):
        logger.debug('external init')
        #         gobject.GObject.__init__(self)
        self.source = conf.get("activities_source")
        self.__gtg_connection = None
        self.rt = None
        self.redmine = None
        self.jira = None
        self.jira_projects = None
        self.jira_issue_types = None
        self.jira_query = None

        try:
            self.__connect(conf)
        except Exception as e:
            error_msg = self.source + ' connection failed: ' + str(e)
            self.on_error(error_msg + ERROR_ADDITIONAL_MESSAGE)
            logger.warn(error_msg)
            self.source = SOURCE_NONE

    def __connect(self, conf):
        if self.source == SOURCE_EVOLUTION and not evolution:
            self.source = SOURCE_NONE  # on failure pretend that there is no evolution
        elif self.source == SOURCE_GTG:
            dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        elif self.source == SOURCE_RT:
            self.__connect_to_rt(conf)
        elif self.source == SOURCE_REDMINE:
            self.__connect_to_redmine(conf)
        elif jira_active and self.source == SOURCE_JIRA:
            self.__connect_to_jira(conf)

    def __connect_to_redmine(self, conf):
        self.redmine_url = conf.get("redmine_url")
        self.redmine_user = conf.get("redmine_user")
        self.redmine_pass = conf.get("redmine_pass")
        try:
            self.redmine_query = json.loads(conf.get("redmine_query"))
        except Exception:
            self.redmine_query = ({})
        if self.redmine_url and self.redmine_user and self.redmine_pass:
            self.redmine = redmine.Redmine(self.redmine_url, auth=(self.redmine_user, self.redmine_pass))
            self.redmine.getIssue(7783)
            if not self.redmine:
                self.source = SOURCE_NONE
        else:
            self.source = SOURCE_NONE

    def __connect_to_jira(self, conf):
        self.jira_url = conf.get("jira_url")
        self.jira_user = conf.get("jira_user")
        self.jira_pass = conf.get("jira_pass")
        self.jira_query = conf.get("jira_query")
        self.jira_category = conf.get("jira_category_field")
        self.jira_fields = ','.join(['summary', self.jira_category, 'issuetype'])
        # self.jira_consumer_key = conf.get("jira_consumer_key")
        # self.jira_access_token = conf.get("jira_access_token")
        # self.jira_access_token_secret = conf.get("jira_access_token_secret")
        # self.jira_key_cert = conf.get("jira_key_cert")
        logger.info("user: %s, pass: *****" % self.jira_user)
        key_cert_data = None
        # if self.jira_key_cert:
        #     if os.path.exists(self.jira_key_cert):
        #         with open(self.jira_key_cert, 'r') as key_cert_file:
        #             key_cert_data = key_cert_file.read()
        #     else:
        #         key_cert_data = self.jira_key_cert

        oauth = self.__parse_jira_oauth_config()
        if (self.jira_url and ((self.jira_user and self.jira_pass) or (oauth['access_token'] and oauth[
            'access_token_secret'] and oauth['consumer_key'] and oauth['key_cert']))):
        # or (self.jira_access_token and self.jira_access_token_secret and self.jira_consumer_key and self.jira_key_cert):
            # options = {'server': self.jira_url}

            options = {'server': self.jira_url}
            basic_auth = None
            if oauth['access_token'] and oauth['access_token_secret'] and oauth['key_cert'] and oauth['consumer_key']:
                basic_auth = {}
            else:
                basic_auth = {self.jira_user, self.jira_pass}
            self.jira = JIRA(options, basic_auth = basic_auth, oauth = oauth, validate = True)
            self.jira_projects = self.__get_jira_projects()
            self.jira_issue_types = self.__get_jira_issue_types()
        else:
            self.source = SOURCE_NONE

    def __parse_jira_oauth_config(self):
        CONFIG_PATH = os.path.join(
            os.path.expanduser('~'), '.jira-python', 'jirashell.ini')
        if not os.path.exists(CONFIG_PATH):
            oauth = {}
        parser = configparser.ConfigParser()
        try:
            parser.read(CONFIG_PATH)
        except configparser.ParsingError as err:
            print("Couldn't read config file at path: {}\n{}".format(
                CONFIG_PATH, err))
            raise
        if parser.has_section('oauth'):
            oauth = {}
            for option, value in parser.items('oauth'):
                oauth[option] = value
        else:
            oauth = {}
        return oauth

    def __connect_to_rt(self, conf):
        self.rt_url = conf.get("rt_url")
        self.rt_user = conf.get("rt_user")
        self.rt_pass = conf.get("rt_pass")
        self.rt_query = conf.get("rt_query")
        self.rt_category = conf.get("rt_category_field")
        if self.rt_url and self.rt_user and self.rt_pass:
            self.rt = rt.Rt(self.rt_url, self.rt_user, self.rt_pass)
            if not self.rt.login():
                self.source = SOURCE_NONE
        else:
            self.source = SOURCE_NONE

    def get_activities(self, query=None):
        if not self.source or not query:
            return []

        if self.source == SOURCE_EVOLUTION:
            return [activity for activity in get_eds_tasks()
                    if query is None or activity['name'].startswith(query)]
        elif self.source == SOURCE_RT:
            activities = self.__extract_from_rt(query, self.rt_query)
            direct_ticket = None
            if query and re.match("^[0-9]+$", query):
                ticket = self.rt.get_ticket(query)
                if ticket:
                    direct_ticket = self.__extract_activity_from_rt_ticket(ticket)
            if direct_ticket:
                activities.append(direct_ticket)
            if len(activities) <= CURRENT_USER_ACTIVITIES_LIMIT and not direct_ticket and len(
                    query) >= MIN_QUERY_LENGTH:
                li = query.split(' ')
                rt_query = " AND ".join(
                    ["(Subject LIKE '%s' OR Owner='%s')" % (q, q) for q in li]) + " AND (Status='new' OR Status='open')"
                # logging.warn(rt_query)
                third_activities = self.__extract_from_rt(query, rt_query, False)
                if activities and third_activities:
                    activities.append({"name": "---------------------", "category": "other open"})
                activities.extend(third_activities)
            return activities
        elif self.source == SOURCE_JIRA:
            activities = self.__extract_from_jira(query, self.jira_query)
            direct_issue = None
            if query and re.match("^[a-zA-Z]+-[0-9]+$", query):
                issue = self.jira.issue(query.upper())
                if issue:
                    direct_issue = self.__extract_activity_from_jira_issue(issue)
            if direct_issue:
                activities.append(direct_issue)
            if len(activities) <= CURRENT_USER_ACTIVITIES_LIMIT and not direct_issue and len(query) >= MIN_QUERY_LENGTH:
                li = query.split(' ')
                fragments = filter(len, [self.__generate_fragment_jira_query(word) for word in li])
                jira_query = " AND ".join(fragments) + " AND resolution = Unresolved order by priority desc, updated desc"
                logging.warn(jira_query)
                third_activities = self.__extract_from_jira('', jira_query)
                if activities and third_activities:
                    activities.append({"name": "---------------------", "category": "other open"})
                activities.extend(third_activities)
            return activities
        elif self.source == SOURCE_REDMINE:
            activities = self.__extract_from_redmine(query, self.redmine_query)
            direct_issue = None
            if query and re.match("^[0-9]+$", query):
                issue = self.redmine.getIssue(query)
                if issue:
                    direct_issue = self.__extract_activity_from_issue(issue)
            if direct_issue:
                activities.append(direct_issue)
            if len(activities) <= CURRENT_USER_ACTIVITIES_LIMIT and not direct_issue and len(query) >= MIN_QUERY_LENGTH:
                redmine_query = ({'status_id': 'open', 'subject': query})
                # logging.warn(redmine_query)
                third_activities = self.__extract_from_redmine(query, redmine_query)
                if activities and third_activities:
                    activities.append({"name": "---------------------", "category": "other open"})
                activities.extend(third_activities)
            return activities
        elif self.source == SOURCE_GTG:
            conn = self.__get_gtg_connection()
            if not conn:
                return []

            activities = []

            tasks = []
            try:
                tasks = conn.GetTasks()
            except dbus.exceptions.DBusException:  # TODO too lame to figure out how to connect to the disconnect signal
                self.__gtg_connection = None
                return self.get_activities(query)  # reconnect

            for task in tasks:
                if query is None or task['title'].lower().startswith(query):
                    name = task['title']
                    if len(task['tags']):
                        name = "%s, %s" % (name, " ".join([tag.replace("@", "#") for tag in task['tags']]))

                    activities.append({"name": name, "category": ""})

            return activities

    def __generate_fragment_jira_query(self, word):
        if word.upper() in self.jira_projects:
            return "project = " + word.upper()
        elif word.lower() in self.jira_issue_types:
            return "issuetype = " + word.lower()
        elif word:
            return "(assignee = '%s' OR summary ~ '%s*')" % (word, word)
        else:
            return ""

    def get_ticket_category(self, activity_id):
        """get activity category depends on source"""
        if not self.source:
            return ""

        if self.source == SOURCE_RT:
            ticket = self.rt.get_ticket(activity_id)
            return self.__extract_cat_from_ticket(ticket)
        elif self.source == SOURCE_JIRA:
            #             try:
            issue = self.jira.issue(activity_id)
            return self.__extract_activity_from_jira_issue(issue)
        # except Exception as e:
        #                 logging.warn(e)
        #                 return ""
        else:
            return ""

    def __extract_activity_from_rt_ticket(self, ticket):
        # activity = {}
        ticket_id = ticket['id']
        # logging.warn(ticket)
        if 'ticket/' in ticket_id:
            ticket_id = ticket_id[7:]
        ticket['name'] = '#' + ticket_id + ': ' + ticket['Subject'].replace(",", " ")
        if 'Owner' in ticket and ticket['Owner'] != self.rt_user:
            ticket['name'] += " (%s)" % ticket['Owner']
        ticket['category'] = self.__extract_cat_from_ticket(ticket)
        ticket['rt_id'] = ticket_id
        return ticket

    def __extract_activity_from_issue(self, issue):
        activity = {}
        issue_id = issue.id
        activity['name'] = '#' + str(issue_id) + ': ' + issue.subject
        activity['rt_id'] = issue_id
        activity['category'] = ""
        return activity

    def __extract_activity_from_jira_issue(self, issue):
        activity = {}
        issue_id = issue.key
        activity['name'] = str(issue_id) + ': ' + issue.fields.summary.replace(",", " ")
        activity['rt_id'] = issue_id
        if hasattr(issue.fields, self.jira_category):
            activity['category'] = str(getattr(issue.fields, self.jira_category))
        else:
            activity['category'] = ""
        if not activity['category']:
            try:
                activity['category'] = getattr(issue.fields, 'issuetype').name
            except Exception as e:
                logger.warn(str(e))
        return activity

    def __extract_from_rt(self, query='', rt_query=None, check_name=True):
        activities = []
        #         results = self.rt.search_simple(rt_query)
        results = self.rt.search_raw(rt_query, [self.rt_category])
        for ticket in results:
            activity = self.__extract_activity_from_rt_ticket(ticket)
            if query is None \
                    or not check_name \
                    or all(item in activity['name'].lower() for item in query.lower().split(' ')):
                activities.append(activity)
        return activities

    def __extract_from_redmine(self, query='', rt_query=None):
        activities = []
        results = self.redmine.getIssues(rt_query)
        for issue in results:
            activity = self.__extract_activity_from_issue(issue)
            if query is None or all(item in activity['name'].lower() for item in query.lower().split(' ')):
                activities.append(activity)
        return activities

    def __extract_from_jira(self, query='', jira_query=None):
        activities = []
        try:
            results = self.__search_jira_issues(jira_query)
            for issue in results:
                activity = self.__extract_activity_from_jira_issue(issue)
                if query is None or all(item in activity['name'].lower() for item in query.lower().split(' ')):
                    activities.append(activity)
        except Exception as e:
            logger.warn(e)
        return activities

    def __get_jira_projects(self):
        return [project.key for project in self.jira.projects()]

    def __get_jira_issue_types(self):
        return [issuetype.name.lower() for issuetype in self.jira.issue_types()]

    @cache_region('short_term', '__extract_from_jira')
    def __search_jira_issues(self, jira_query=None):
        return self.jira.search_issues(jira_query, fields=self.jira_fields, maxResults=100)

    def __extract_cat_from_ticket(self, ticket):
        category = DEFAULT_RT_CATEGORY
        if 'Queue' in ticket:
            category = ticket['Queue']
        if self.rt_category in ticket and ticket[self.rt_category]:
            category = ticket[self.rt_category]
        # owner = None
        #        if 'Owner' in ticket:
        #            owner = ticket['Owner']
        #        if owner and owner!=self.rt_user:
        #            category += ":"+owner
        return category

    def __get_gtg_connection(self):
        bus = dbus.SessionBus()
        if self.__gtg_connection and bus.name_has_owner("org.gnome.GTG"):
            return self.__gtg_connection

        if bus.name_has_owner("org.gnome.GTG"):
            self.__gtg_connection = dbus.Interface(bus.get_object('org.gnome.GTG', '/org/gnome/GTG'),
                                                   dbus_interface='org.gnome.GTG')
            return self.__gtg_connection
        else:
            return None

    def on_error(self, msg):
        md = gtk.MessageDialog(None,
                               gtk.DIALOG_DESTROY_WITH_PARENT, gtk.MESSAGE_ERROR,
                               gtk.BUTTONS_CLOSE, msg)
        md.run()
        md.destroy()


def get_eds_tasks():
    try:
        sources = ecal.list_task_sources()
        tasks = []
        if not sources:
            # BUG - http://bugzilla.gnome.org/show_bug.cgi?id=546825
            sources = [('default', 'default')]

        for source in sources:
            category = source[0]

            data = ecal.open_calendar_source(source[1], ecal.CAL_SOURCE_TYPE_TODO)
            if data:
                for task in data.get_all_objects():
                    if task.get_status() in [ecal.ICAL_STATUS_NONE, ecal.ICAL_STATUS_INPROCESS]:
                        tasks.append({'name': task.get_summary(), 'category': category})
        return tasks
    except Exception, e:
        logger.warn(e)
        return []
