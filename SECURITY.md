# Security

Loop Builder runs on your computer and serves its editor only to that computer (127.0.0.1). It also answers only
its own pages: a request must name this computer as its host (so a website can't reach it by pointing a name of its
own at 127.0.0.1), and a change must come from Loop Builder's own page or from no page at all (so a website can't
post a form to it).

If you find a security problem, please report it privately through GitHub's
[private vulnerability reporting](https://github.com/mhuot/loop-builder/security/advisories/new) instead of
a public issue. Fixes go into the next release.
