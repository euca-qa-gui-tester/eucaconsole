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
Pyramid views for Eucalyptus and AWS key pairs

"""
import simplejson as json

from boto.exception import BotoServerError
from pyramid.httpexceptions import HTTPFound
from pyramid.view import view_config
from pyramid.response import Response

from ..forms.keypairs import KeyPairForm, KeyPairImportForm, KeyPairDeleteForm
from ..i18n import _
from ..models import Notification
from ..views import BaseView, LandingPageView, JSONResponse
from . import boto_error_handler


class KeyPairsView(LandingPageView):
    def __init__(self, request):
        super(KeyPairsView, self).__init__(request)
        self.initial_sort_key = 'name'
        self.prefix = '/keypairs'
        self.delete_form = KeyPairDeleteForm(self.request, formdata=self.request.params or None)

    @view_config(route_name='keypairs', renderer='../templates/keypairs/keypairs.pt')
    def keypairs_landing(self):
        json_items_endpoint = self.request.route_path('keypairs_json')
        # filter_keys are passed to client-side filtering in search box
        self.filter_keys = ['name', 'fingerprint']
        # sort_keys are passed to sorting drop-down
        self.sort_keys = [
            dict(key='name', name=_(u'Name: A to Z')),
            dict(key='-name', name=_(u'Name: Z to A')),
        ]

        return dict(
            filter_fields=self.filter_fields,
            filter_keys=self.filter_keys,
            sort_keys=self.sort_keys,
            prefix=self.prefix,
            initial_sort_key=self.initial_sort_key,
            json_items_endpoint=json_items_endpoint,
            delete_form=self.delete_form,
        )


class KeyPairsJsonView(BaseView):
    def __init__(self, request):
        super(KeyPairsJsonView, self).__init__(request)
        self.conn = self.get_connection()

    @view_config(route_name='keypairs_json', renderer='json', request_method='GET')
    def keypairs_json(self):
        keypairs = []
        with boto_error_handler(self.request):
            for keypair in self.get_items():
                keypairs.append(dict(
                    name=keypair.name,
                    fingerprint=keypair.fingerprint,
                ))
            return dict(results=keypairs)

    def get_items(self):
        ret = []
        if self.conn:
            ret = self.conn.get_all_key_pairs()
        return ret


class KeyPairView(BaseView):
    """Views for single Key Pair"""
    TEMPLATE = '../templates/keypairs/keypair_view.pt'

    def __init__(self, request):
        super(KeyPairView, self).__init__(request)
        self.conn = self.get_connection()
        self.keypair = self.get_keypair()
        self.keypair_route_id = self.request.matchdict.get('id')
        self.keypair_form = KeyPairForm(self.request, keypair=self.keypair, formdata=self.request.params or None)
        self.keypair_import_form = KeyPairImportForm(
            self.request, keypair=self.keypair, formdata=self.request.params or None)
        self.delete_form = KeyPairDeleteForm(self.request, formdata=self.request.params or None)
        self.render_dict = dict(
            keypair=self.keypair,
            keypair_route_id=self.keypair_route_id,
            keypair_form=self.keypair_form,
            keypair_import_form=self.keypair_import_form,
            delete_form=self.delete_form,
            keypair_names=self.get_keypair_names(),
        )

    def get_keypair(self):
        keypair_param = self.request.matchdict.get('id')
        if keypair_param == "new" or keypair_param == "new2":
            return None
        keypairs_param = [keypair_param]
        keypairs = []
        if self.conn:
            try:
                keypairs = self.conn.get_all_key_pairs(keynames=keypairs_param)
            except BotoServerError as err:
                return None
        keypair = keypairs[0] if keypairs else None
        return keypair 

    @view_config(route_name='keypair_view', renderer=TEMPLATE)
    def keypair_view(self):
        session = self.request.session
        new_keypair_created = False
        # Check if the session contains the new keypair material information
        if self._has_file_():
            new_keypair_created = True

        self.render_dict['keypair_created'] = new_keypair_created
        return self.render_dict

    def get_keypair_names(self):
        keypairs = []
        with boto_error_handler(self.request):
            if self.conn:
                keypairs = [k.name for k in self.conn.get_all_key_pairs()]
        return sorted(set(keypairs))

    @view_config(route_name='keypair_create', request_method='POST', renderer=TEMPLATE)
    def keypair_create(self):
        if self.keypair_form.validate():
            name = self.request.params.get('name')
            session = self.request.session
            new_keypair = None
            location = self.request.route_path('keypair_view', id=name)
            with boto_error_handler(self.request, location):
                self.log_request(_(u"Creating keypair ")+name)
                new_keypair = self.conn.create_key_pair(name)
                # Store the new keypair material information in the session
                self._store_file_(new_keypair.name+".pem",
                                  'application/x-pem-file;charset=ISO-8859-1',
                                  new_keypair.material)
                msg_template = _(u'Successfully created key pair {keypair}')
                msg = msg_template.format(keypair=name)
            if self.request.is_xhr:
                keypair_material = new_keypair.material if new_keypair else None
                resp_body = json.dumps(dict(message=msg, payload=keypair_material))
                return Response(status=200, body=resp_body, content_type='application/x-pem-file;charset=ISO-8859-1')
            else:
                self.request.session.flash(msg, queue=Notification.SUCCESS)
                location = self.request.route_path('keypair_view', id=name)
                return HTTPFound(location=location)
        if self.request.is_xhr:
            form_errors = ', '.join(self.keypair_form.get_errors_list())
            return JSONResponse(status=400, message=form_errors)  # Validation failure = bad request
        else:
            self.request.error_messages = self.keypair_form.get_errors_list()
            return self.render_dict

    @view_config(route_name='keypair_import', request_method='POST', renderer=TEMPLATE)
    def keypair_import(self):
        if self.keypair_form.validate():
            name = self.request.params.get('name')
            key_material = self.request.params.get('key_material')
            msg = ""
            material = ""
            location = self.request.route_path('keypair_view', id=name)
            with boto_error_handler(self.request, location):
                self.log_request(_(u"Importing keypair ")+name)
                new_keypair = self.conn.import_key_pair(name, key_material)
                material = new_keypair.material
                msg_template = _(u'Successfully imported key pair {keypair}')
                msg = msg_template.format(keypair=name)
                self.request.session.flash(msg, queue=Notification.SUCCESS)
            return HTTPFound(location=location)

        return self.render_dict

    @view_config(route_name='keypair_delete', request_method='POST', renderer=TEMPLATE)
    def keypair_delete(self):
        if self.delete_form.validate():
            name = self.request.params.get('name')
            location = self.request.route_path('keypairs')
            with boto_error_handler(self.request, location):
                self.log_request(_(u"Deleting keypair ")+name)
                self.conn.delete_key_pair(name)
                prefix = _(u'Successfully deleted keypair')
                msg = '{0} {1}'.format(prefix, name)
                self.request.session.flash(msg, queue=Notification.SUCCESS)
            return HTTPFound(location=location)

        return self.render_dict


