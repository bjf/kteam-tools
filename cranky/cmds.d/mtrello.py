#!/usr/bin/env python3
#

import os
from trello                             import TrelloClient

class MTrello(object):
    '''
    '''
    def __init__(self):
        '''
        '''
        self.client = TrelloClient(api_key=os.environ['TRELLO_API_KEY'], api_secret=os.environ['TRELLO_API_SECRET'], token=os.environ['PY_TRELLO_OAUTH_TOKEN'], token_secret=os.environ['PY_TRELLO_OAUTH_TOKEN_SECRET'])

    def board_find(self, name):
        retval = None
        for board in self.client.list_boards():
            if board.name == name:
                retval = board
                break
        return retval

    def find_me(self, name=None):
        retval = None
        if name is None:
            name = os.environ['TRELLO_FULLNAME']
        for member in self.org_find_mine().get_members():
            if member.full_name == name:
                retval = member
                break
        return retval

    def org_find_mine(self):
        retval = None
        orgs = self.client.list_organizations()
        for org in orgs:
            if org.name == 'kernelteam2':
                retval = org
                break
        return retval

    def list_find_on_board(self, board, name):
        retval = None
        board_lists = board.list_lists()
        for l in board_lists:
            if l.name == name:
                retval = l
                break
        return retval

    def card_find_on_list_on_board(self, board_name, list_name, card_name):
        retval = None
        cards = self.list_find_on_board(self.board_find(board_name), list_name).list_cards()
        for card in cards:
            if card.name == card_name:
                retval = card
                break
        return retval
