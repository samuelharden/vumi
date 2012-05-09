# -*- test-case-name: vumi.transports.mtech_ussd.tests.test_mtech_ussd -*-

from xml.etree import ElementTree as ET

import redis

from vumi.message import TransportUserMessage
from vumi.transports.httprpc import HttpRpcTransport
from vumi.application.session import SessionManager


class MtechUssdTransport(HttpRpcTransport):

    def setup_transport(self):
        super(MtechUssdTransport, self).setup_transport()
        self.redis_config = self.config.get('redis', {})
        self.r_prefix = "mtech_ussd:%s" % self.transport_name
        session_timeout = int(self.config.get("ussd_session_timeout", 600))
        self.r_server = self.connect_to_redis()
        self.session_manager = SessionManager(
            self.r_server, self.r_prefix, max_session_length=session_timeout)

    def teardown_transport(self):
        self.session_manager.stop()
        super(MtechUssdTransport, self).teardown_transport()

    def connect_to_redis(self):
        return redis.Redis(**self.redis_config)

    def save_session(self, session_id, from_addr, to_addr):
        return self.session_manager.create_session(
            session_id, from_addr=from_addr, to_addr=to_addr)

    def handle_raw_inbound_message(self, msgid, request):
        body = ET.fromstring(request.content.read())

        # We always get these.
        session_id = body.find('session_id').text
        page_id = body.find('page_id').text
        content = body.find('data').text

        if page_id == '0':
            # This is a new session.
            session = self.save_session(
                session_id,
                from_addr=body.find('mobile_number').text,
                to_addr=body.find('gate').text)  # ???
            session_event = TransportUserMessage.SESSION_NEW
        else:
            # This is an existing session.
            session = self.session_manager.load_session(session_id)
            session_event = TransportUserMessage.SESSION_RESUME

        transport_metadata = {'session_id': session_id}
        self.publish_message(
                message_id=msgid,
                content=content,
                to_addr=session['to_addr'],
                from_addr=session['from_addr'],
                session_event=session_event,
                transport_name=self.transport_name,
                transport_type=self.config.get('transport_type'),
                transport_metadata=transport_metadata,
                )

    def handle_outbound_message(self, message):
        mur = MtechUssdResponse(message['transport_metadata']['session_id'])
        mur.add_text(message['content'])
        if message['session_event'] != TransportUserMessage.SESSION_CLOSE:
            mur.add_freetext_option()
        self.finish_request(message['in_reply_to'],
                            unicode(mur).encode('utf-8'))


class MtechUssdResponse(object):
    def __init__(self, session_id):
        self.session_id = session_id
        self.text = []
        self.nav = []

    def add_title(self, title):
        self.text.insert(0, '<title>%s</title>' % (title,))

    def add_text(self, text):
        self.text.append('<div>%s</div>' % (text,))

    def add_menu_item(self, text, option):
        self.nav.append((
                '<link accesskey="%(option)s" pageId="index%(option)s">'
                '%(text)s</link>') % {'text': text, 'option': option})

    def add_freetext_option(self):
        self.nav.append('<link accesskey="*" pageId="indexX" />')

    def __str__(self):
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<page version="2.0">',
            '  <session_id>%s</session_id>' % (self.session_id,),
            ]
        lines.extend('  %s' % (line,) for line in self.text)
        if self.nav:
            lines.append('  <navigation>')
            lines.extend('    %s' % (line,) for line in self.nav)
            lines.append('  </navigation>')
        lines.append('</page>')

        return '\n'.join(lines)