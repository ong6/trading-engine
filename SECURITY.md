# Security

The engine holds no credentials, connects to no broker and moves no money. It
fetches public market data and writes to a local DuckDB file.

If you find something that leaks data off the box, executes untrusted input, or
lets a discretionary ticket bypass a risk gate, open a private security advisory
on GitHub rather than a public issue.
