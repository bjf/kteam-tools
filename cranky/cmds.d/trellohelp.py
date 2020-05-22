#!/usr/bin/env python3
#

import sys
import os

sys.path.append(os.path.realpath(os.path.join(os.path.dirname(__file__), '..', '..', 'stable')))
from trellotool.trellotool              import TrelloTool

class TrelloHelp():
    def __init__(self):
        self.tt = TrelloTool()
        self.tt.assert_authenticated()
        self.trello = self.tt.trello
        self.org = 'kernelteam2'

    def board_find(self, board_name):
        retval = None
        for board in self.trello.organization_boards(self.org):
            if board['name'] == board_name:
                retval = board
                break
        return retval

    def list_find_on_board(self, board, list_name):
        retval = None
        for alist in self.trello.board_lists(board['id']):
            if alist['name'] == list_name:
                retval = alist
                break
        return retval

    def card_find_on_list_on_board(self, board_name, list_name, card_name):
        retval = None
        the_board = self.board_find(board_name)
        the_list  = self.list_find_on_board(the_board, list_name)
        for card in self.trello.list_cards(the_list['id']):
            if card['name'] == card_name:
                retval = card
                break
        return retval

    @property
    def me(self):
        return self.trello.member_record('me')
