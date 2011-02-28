#
# Copyright (C) 2011 mooz
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.
#

import sys
import signal
import curses

from itertools import islice

def log(name, s = ""):
    with open("/tmp/log", "a") as f:
        f.write(name + " : " + str(s) + "\n")

class TerminateLoop(Exception):
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return repr(self.value)

class Percol:
    def __init__(self, target):
        self.stdin  = target["stdin"]
        self.stdout = target["stdout"]
        self.stderr = target["stderr"]

        self.collection = self.stdin.read().split("\n")
        self.target = target

        self.output_buffer = []

        self.colors = {
            "normal_line"   : 1,
            "selected_line" : 2,
            "marked_line"   : 3,
            "keyword"       : 4,
        }

    def __enter__(self):
        self.screen = curses.initscr()

        curses.start_color()
        # foreground, background
        curses.init_pair(self.colors["normal_line"]     , curses.COLOR_WHITE,  curses.COLOR_BLACK)   # normal
        curses.init_pair(self.colors["selected_line"]   , curses.COLOR_WHITE,  curses.COLOR_MAGENTA) # line selected
        curses.init_pair(self.colors["marked_line"]     , curses.COLOR_BLACK,  curses.COLOR_CYAN)    # line marked
        curses.init_pair(self.colors["keyword"]         , curses.COLOR_YELLOW, curses.COLOR_BLACK)   # keyword

        signal.signal(signal.SIGINT, lambda signum, frame: None)

        curses.noecho()
        curses.cbreak()

        return self

    def __exit__(self, exc_type, exc_value, traceback):
        curses.endwin()

        if self.stdout:
            self.stdout.write("".join(self.output_buffer))

    def output(self, s):
        # delay actual output (wait curses to finish)
        self.output_buffer.append(s)

    def update_candidates_max(self):
        y, x = self.screen.getmaxyx()

        self.WIDTH          = x
        self.CANDIDATES_MAX = y - 1

    def init_display(self):
        self.update_candidates_max()
        self.do_search("")
        self.refresh_display()

    def loop(self):
        self.status = {
            "index"   : 0,
            "rows "   : 0,
            "results" : None,
            "marks"   : None,
            "query"   : None,
        }

        self.results_cache = {}

        old_query = self.status["query"] = ""

        self.init_display()

        while True:
            try:
                self.handle_key(self.screen.getch())

                query = self.status["query"]

                log("query", query)

                if query != old_query:
                    self.do_search(query)
                    old_query = query

                self.refresh_display()
            except TerminateLoop:
                break

    def do_search(self, query):
        self.status["index"] = 0

        if self.results_cache.has_key(query):
            self.status["results"] = self.results_cache[query]
            log("Used cache", query)
        else:
            self.status["results"] = [result for result in islice(self.search(query), self.CANDIDATES_MAX)]
            self.results_cache[query] = self.status["results"]

        results_count        = len(self.status["results"])
        self.status["marks"] = [False] * results_count
        self.status["rows"]  = results_count

    def refresh_display(self):
        self.screen.erase()
        self.display_results()
        self.display_prompt()
        self.screen.refresh()

    def get_candidate(self, index):
        results = self.status["results"]

        try:
            return results[index][0]
        except IndexError:
            return None

    def get_selected_candidate(self, ):
        return self.get_candidate(self.status["index"])

    def display_line(self, s, color):
        self.screen.addnstr(pos, 0, line, self.WIDTH, line_color)

        # add padding
        line_len    = len(line)
        padding_len = self.WIDTH - line_len
        if padding_len > 0:
            self.screen.addstr(pos, line_len, " " * padding_len, line_color)

    def display_result(self, pos, result, is_current = False, is_marked = False):
        line, pairs = result

        if is_current:
            line_color = curses.color_pair(self.colors["selected_line"])
        else:
            if is_marked:
                line_color = curses.color_pair(self.colors["marked_line"])
            else:
                line_color = curses.color_pair(self.colors["normal_line"])

        keyword_color = curses.color_pair(self.colors["keyword"])

        self.screen.addnstr(pos, 0, line, self.WIDTH, line_color)

        # add padding
        line_len    = len(line)
        padding_len = self.WIDTH - line_len
        if padding_len > 0:
            self.screen.addstr(pos, line_len, " " * padding_len, line_color)

        # highlight not-selected lines only
        if not is_current:
            for q, offsets in pairs:
                q_len = len(q)
                for offset in offsets:
                    self.screen.addnstr(pos, offset, line[offset:offset + q_len],
                                        self.WIDTH - offset, keyword_color)

    def display_results(self, ):
        voffset = 1
        for i, result in enumerate(self.status["results"]):
            try:
                self.display_result(i + voffset, result,
                                    is_current = i == self.status["index"],
                                    is_marked = self.status["marks"][i])
            except curses.error:
                pass

    def display_prompt(self, query = None):
        if not query:
            query = self.status["query"]
        # display prompt
        try:
            prompt_str = "QUERY> " + query
            self.screen.addnstr(0, 0, prompt_str, self.WIDTH)
            self.screen.move(0, len(prompt_str))
        except curses.error:
            pass

    def handle_special(self, s, ch):
        ENTER     = 10
        BACKSPACE = 127
        DELETE    = 126
        CTRL_SPC  = 0
        CTRL_A    = 1
        CTRL_B    = 2
        CTRL_C    = 3
        CTRL_D    = 4
        CTRL_H    = 8
        CTRL_N    = 14
        CTRL_P    = 16

        def select_next():
            self.status["index"] = (self.status["index"] + 1) % self.status["rows"]

        def select_previous():
            self.status["index"] = (self.status["index"] - 1) % self.status["rows"]

        def toggle_mark():
            self.status["marks"][self.status["index"]] ^= True

        def finish():
            any_marked = False

            # TODO: make this action customizable
            def execute_action(arg):
                self.output("{0}\n".format(arg))

            for i, marked in enumerate(self.status["marks"]):
                if marked:
                    any_marked = True
                    execute_action(get_candidate(i))

            if not any_marked:
                execute_action(get_selected_candidate())

        if ch in (BACKSPACE, CTRL_H):
            s = s[:-1]
        elif ch == CTRL_A:
            s = ""
        elif ch == CTRL_N:
            select_next()
        elif ch == CTRL_P:
            select_previous()
        elif ch == CTRL_SPC:
            # mark
            toggle_mark()
            select_next()
        elif ch == ENTER:
            finish()
            raise TerminateLoop("Bye!")
        elif ch < 0:
            raise TerminateLoop("Bye!")

        return s

    def handle_key(self, ch):
        try:
            if 32 <= ch <= 126:
                self.status["query"] += chr(ch)
            elif ch == curses.KEY_RESIZE:
                # resize
                self.update_candidates_max()
            else:
                self.status["query"] = self.handle_special(self.status["query"], ch)
        except ValueError:
            pass

        # DEBUG: display key code
        self.screen.addnstr(0, 30, "<keycode: {0}>".format(ch), self.WIDTH)

    # ============================================================ #
    # Find
    # ============================================================ #

    def find_all(self, needle, haystack):
        stride = len(needle)

        if stride == 0:
            return [0]

        start  = 0
        res    = []

        while True:
            found = haystack.find(needle, start)
            if found < 0:
                break
            res.append(found)
            start = found + stride

        return res

    def and_find(self, queries, line):
        res = []

        for q in queries:
            if not q in line:
                return None
            else:
                res.append((q, self.find_all(q, line)))

        return res

    def search(self, query):
        for line in self.collection:
            res = self.and_find(query.split(" "), line)

            if res:
                yield line, res
