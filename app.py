"""Local text/LaTeX editor for the handwriting PDF renderer. Run: python app.py."""
import queue
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from hands import available_styles, find_hand

HERE = Path(__file__).resolve().parent
SAMPLE = r"""My handwritten notes

Type or paste your text here, or open a text file.
Inline math goes between dollar signs: $a^2 + b^2 = c^2$.

For a larger equation, use double dollar signs:
$$
x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}
$$
"""


def render_document(text, output, font=None, hand_math=True, cleanup=False):
    """Render in an isolated process; keep input and intermediate HTML temporary."""
    font = font or available_styles()[0]
    hand = find_hand(font)
    font_options = list(hand.options) if hand else ['--font', font]
    with tempfile.TemporaryDirectory(prefix='handwriting-') as directory:
        source = Path(directory) / 'input.txt'
        source.write_text(text, encoding='utf-8')
        command = [sys.executable, str(HERE / 'handwrite.py'), str(source),
                   str(output), *font_options, '--keep-html',
                   str(Path(directory) / 'render.html')]
        if hand_math:
            command.append('--hand-math')
        if not cleanup:
            command.append('--clean')
        result = subprocess.run(command, capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=180)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip()
                               or 'PDF generation failed.')
        return result.stderr.strip()


class HandwritingApp:
    def __init__(self, root):
        self.root = root
        self.results = queue.Queue()
        self.busy = False
        self.output = None
        root.title('Handwriting — Text and math to PDF')
        root.geometry('880x720')
        root.minsize(650, 500)
        frame = ttk.Frame(root, padding=20)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Turn your notes into handwriting',
                  font=('', 20, 'bold')).pack(anchor='w')
        ttk.Label(frame, text='Paste text or open a UTF-8 .txt, .md, or .tex file. '
                  'Everything is processed on your computer.').pack(anchor='w', pady=(8, 14))
        toolbar = ttk.Frame(frame)
        toolbar.pack(fill='x')
        ttk.Button(toolbar, text='Open text / math file…', command=self.open_file).pack(side='left')
        ttk.Label(toolbar, text='Handwriting style').pack(side='left', padx=(20, 8))
        styles = available_styles()
        self.font = tk.StringVar(value=styles[0])
        ttk.Combobox(toolbar, textvariable=self.font, values=styles,
                     state='readonly', width=24).pack(side='left')
        self.editor = scrolledtext.ScrolledText(frame, wrap='word', undo=True,
                                               font=('TkFixedFont', 13), padx=12, pady=12)
        self.editor.pack(fill='both', expand=True, pady=14)
        self.editor.insert('1.0', SAMPLE)
        ttk.Label(frame, text=r'Math: $x^2$ inline, $$\frac{a}{b}$$ on its own line. '
                  'Full LaTeX documents, PDF, Word, and image imports are not supported.',
                  wraplength=800).pack(anchor='w')
        self.hand_math = tk.BooleanVar(value=True)
        self.cleanup = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text='Use handwriting for math characters '
                        '(unsupported symbols stay typeset)', variable=self.hand_math).pack(anchor='w', pady=(12, 0))
        ttk.Checkbutton(frame, text='Clean up duplicated text from a messy paste',
                        variable=self.cleanup).pack(anchor='w')
        actions = ttk.Frame(frame)
        actions.pack(fill='x', pady=(14, 8))
        self.generate = ttk.Button(actions, text='Save handwritten PDF…', command=self.save)
        self.generate.pack(side='left')
        self.open_button = ttk.Button(actions, text='Open PDF', command=self.open_pdf, state='disabled')
        self.open_button.pack(side='left', padx=8)
        self.status = tk.StringVar(value='Ready')
        ttk.Label(frame, textvariable=self.status, wraplength=800).pack(anchor='w')
        root.protocol('WM_DELETE_WINDOW', self.close)

    def open_file(self):
        path = filedialog.askopenfilename(filetypes=[('Text and LaTeX', '*.txt *.md *.tex')])
        if not path:
            return
        try:
            text = Path(path).read_text(encoding='utf-8-sig')
        except (OSError, UnicodeError) as error:
            messagebox.showerror('Cannot open file', f'Choose a UTF-8 text file.\n\n{error}')
            return
        self.editor.delete('1.0', 'end')
        self.editor.insert('1.0', text)
        self.status.set(f'Loaded {Path(path).name}')

    def save(self):
        if self.busy:
            return
        text = self.editor.get('1.0', 'end-1c')
        if not text.strip():
            messagebox.showinfo('Add some text', 'Type some text or open a file first.')
            return
        output = filedialog.asksaveasfilename(defaultextension='.pdf',
                    initialfile='handwritten-notes.pdf', filetypes=[('PDF document', '*.pdf')])
        if not output:
            return
        options = (text, output, self.font.get(), self.hand_math.get(), self.cleanup.get())
        self.busy = True
        self.generate.config(state='disabled')
        self.open_button.config(state='disabled')
        self.status.set('Creating your handwritten PDF…')

        def work():
            try:
                notes = render_document(*options)
                self.results.put((output, notes, None))
            except Exception as error:
                self.results.put((None, '', str(error)))

        threading.Thread(target=work, daemon=True).start()
        self.root.after(100, self.poll)

    def poll(self):
        try:
            output, notes, error = self.results.get_nowait()
        except queue.Empty:
            self.root.after(100, self.poll)
            return
        self.busy = False
        self.generate.config(state='normal')
        if error:
            self.status.set('Could not create PDF. See the error for details.')
            messagebox.showerror('Rendering failed', error)
            return
        self.output = Path(output)
        self.open_button.config(state='normal')
        self.status.set(f'Saved {output}')
        if notes:
            messagebox.showwarning('PDF saved — review rendering notes', notes)

    def open_pdf(self):
        if self.output:
            webbrowser.open(self.output.resolve().as_uri())

    def close(self):
        if self.busy:
            messagebox.showinfo('Creating PDF', 'Please wait for the current PDF to finish.')
            return
        self.root.destroy()


if __name__ == '__main__':
    root = tk.Tk()
    HandwritingApp(root)
    root.mainloop()
