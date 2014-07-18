# -*- coding: utf-8 -*-
# Copyright 2013-2014 Eucalyptus Systems, Inc.
#
# Redistribution and use of this software in source and binary forms,
# with or without modification, are permitted provided that the following
# conditions are met:
#
# Redistributions of source code must retain the above copyright notice,
# this list of conditions and the following disclaimer.
#
# Redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""
Pyramid views for Login/Logout

"""
import base64
import logging
from urllib2 import HTTPError, URLError
from urlparse import urlparse

from pyramid.httpexceptions import HTTPFound
from pyramid.security import NO_PERMISSION_REQUIRED, remember, forget
from pyramid.settings import asbool
from pyramid.view import view_config, forbidden_view_config

from ..forms.login import EucaLoginForm, EucaLogoutForm, AWSLoginForm
from ..i18n import _
from ..models.auth import AWSAuthenticator, ConnectionManager
from ..views import BaseView
from ..views import JSONResponse
from ..constants import AWS_REGIONS


@forbidden_view_config()
def redirect_to_login_page(request):
    login_url = request.route_path('login')
    return HTTPFound(login_url)


class LoginView(BaseView):
    TEMPLATE = '../templates/login.pt'

    def __init__(self, request):
        super(LoginView, self).__init__(request)
        self.euca_login_form = EucaLoginForm(self.request, formdata=self.request.params or None)
        self.aws_login_form = AWSLoginForm(self.request, formdata=self.request.params or None)
        self.aws_enabled = asbool(request.registry.settings.get('enable.aws'))
        referrer = urlparse(self.request.url).path
        login_url = self.request.route_path('login')
        logout_url = self.request.route_path('logout')
        if referrer in [login_url, logout_url]:
            referrer = '/'  # never use the login form (or logout view) itself as came_from
        self.came_from = self.sanitize_url(self.request.params.get('came_from', referrer))
        self.login_form_errors = []
        self.duration = str(int(self.request.registry.settings.get('session.cookie_expires')) + 60)
        self.secure_session = asbool(self.request.registry.settings.get('session.secure', False))
        self.https_proxy = self.request.environ.get('HTTP_X_FORWARDED_PROTO') == 'https'
        self.https_scheme = self.request.scheme == 'https'
        self.render_dict = dict(
            https_required=self.show_https_warning(),
            euca_login_form=self.euca_login_form,
            aws_login_form=self.aws_login_form,
            login_form_errors=self.login_form_errors,
            aws_enabled=self.aws_enabled,
            duration=self.duration,
            came_from=self.came_from,
        )

    def show_https_warning(self):
        if any([self.https_proxy, self.https_scheme]) and not self.secure_session:
            return True
        if self.secure_session and not (any([self.https_proxy, self.https_scheme])):
            return True
        return False

    @view_config(route_name='login', request_method='GET', renderer=TEMPLATE, permission=NO_PERMISSION_REQUIRED)
    @forbidden_view_config(request_method='GET', renderer=TEMPLATE)
    def login_page(self):
        if self.request.is_xhr:
            message = getattr(self.request.exception, 'message', _(u"Session Timed Out"))
            status = getattr(self.request.exception, 'status', "403 Forbidden")
            status = int(status[:status.index(' ')]) or 403
            return JSONResponse(status=status, message=message)
        return self.render_dict

    @view_config(route_name='login', request_method='POST', renderer=TEMPLATE, permission=NO_PERMISSION_REQUIRED)
    def handle_login(self):
        """Handle login form post"""

        login_type = self.request.params.get('login_type')

        if login_type == 'Eucalyptus':
            return self.handle_euca_login()
        elif login_type == 'AWS':
            return self.handle_aws_login()

        return self.render_dict

    def handle_euca_login(self):
        new_passwd = None
        auth = self.get_connection(conn_type='sts', cloud_type='euca')
        session = self.request.session

        if self.euca_login_form.validate():
            account = self.request.params.get('account')
            username = self.request.params.get('username')
            password = self.request.params.get('password')
            try:
                creds = auth.authenticate(
                    account=account, user=username, passwd=password,
                    new_passwd=new_passwd, timeout=8, duration=self.duration)
                user_account = '{user}@{account}'.format(user=username, account=account)
                # self.invalidate_connection_cache()
                session.invalidate()  # Refresh session
                session['cloud_type'] = 'euca'
                session['account'] = account
                session['username'] = username
                session['session_token'] = creds.session_token
                session['access_id'] = creds.access_key
                session['secret_key'] = creds.secret_key
                session['region'] = 'euca'
                session['username_label'] = '{user}@{account}'.format(user=username, account=account)
                headers = remember(self.request, user_account)
                return HTTPFound(location=self.came_from, headers=headers)
            except HTTPError, err:
                logging.info("http error "+str(vars(err)))
                if err.code == 403:  # password expired
                    changepwd_url = self.request.route_path('changepassword')
                    return HTTPFound(changepwd_url+("?expired=true&account=%s&username=%s" % (account, username)))
                elif err.msg == u'Unauthorized':
                    msg = _(u'Invalid user/account name and/or password.')
                    self.login_form_errors.append(msg)
            except URLError, err:
                logging.info("url error "+str(vars(err)))
                #if str(err.reason) == 'timed out':
                # opened this up since some other errors should be reported as well.
                msg = _(u'No response from host')
                self.login_form_errors.append(msg)
        return self.render_dict

    def handle_aws_login(self):
        session = self.request.session
        if self.aws_login_form.validate():
            package = self.request.params.get('package')
            package = base64.decodestring(package)
            aws_region = self.request.params.get('aws-region')
            try:
                auth = AWSAuthenticator(package=package)
                creds = auth.authenticate(timeout=10)
                default_region = self.request.registry.settings.get('aws.default.region', 'us-east-1')
                # self.invalidate_connection_cache()
                session.invalidate()  # Refresh session
                session['cloud_type'] = 'aws'
                session['session_token'] = creds.session_token
                session['access_id'] = creds.access_key
                session['secret_key'] = creds.secret_key
                last_visited_aws_region = [reg for reg in AWS_REGIONS if reg.get('name') == aws_region]
                session['region'] = aws_region if last_visited_aws_region else default_region
                session['username_label'] = '{user}...@AWS'.format(user=creds.access_key[:8])
                # Save EC2 Connection object in cache
                ConnectionManager.aws_connection(
                    default_region, creds.access_key, creds.secret_key, creds.session_token, 'ec2')
                headers = remember(self.request, creds.access_key[:8])
                return HTTPFound(location=self.came_from, headers=headers)
            except HTTPError, err:
                if err.msg == 'Forbidden':
                    msg = _(u'Invalid access key and/or secret key.')
                    self.login_form_errors.append(msg)
        return self.render_dict


class LogoutView(BaseView):
    def __init__(self, request):
        super(LogoutView, self).__init__(request)
        self.request = request
        self.login_url = request.route_path('login')
        self.euca_logout_form = EucaLogoutForm(self.request, formdata=self.request.params or None)

    @view_config(route_name='logout', request_method='POST')
    def logout(self):
        if self.euca_logout_form.validate():
            forget(self.request)
            self.request.session.invalidate()
            # self.invalidate_connection_cache()
            return HTTPFound(location=self.login_url)

