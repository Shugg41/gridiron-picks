# Week 9 — what the numbers do not know

Researched 27 October. Two independent numbers per game (the sportsbook
spread, and FPI) are in `data/opinions.tsv`. These are the things that
move a pick and are not in either of them.

The general lesson of the week: **FPI does not know about injuries.** It
rates a team on what it has done, so on any game where the news has
changed who is playing, FPI is stale and the market is not. Where the
two disagree this week, the market is usually right and FPI is usually
behind an injury.

## The news that changes a number

**OSU @ USC — Ohio State's QB is out.** Julian Sayin, throwing shoulder,
hurt at Indiana; Day is planning for a possible absence through the rest
of the season, and has not named a starter between Luke Fahey and Tavien
St. Clair. The market has absorbed it: the line went 7.5 to 6.5 and back
to about 7. FPI has not — it still rates Ohio State as though Sayin is
playing, which is why the blend said 70% when the market says 65%. Still
Ohio State; it is not the 70% game the model thought.

**ILL @ MD — Illinois' QB is out and it has not mattered.** Katin Houser
broke his hand on 10 October, out four to six weeks. Freshman Michael
Clayton II has started since and beat Oregon 21-10 on 24 October.
Maryland is 2-5, 0-4, and just made its DB coach interim head coach.
Illinois -2.5 is fair and the situation favours them.

**NW @ ORE — Oregon is in trouble.** Dante Moore gone for the season
with a concussion, Dylan Raiola threw for 246 yards with no touchdowns
and two fumbles in the loss at Illinois, the offence was shut out in the
second half, and Oregon fired its first-year offensive coordinator the
next day. Raiola has said the playoff is "probably out of reach". FPI
rates Oregon at 64% off earlier form; the market says 58%. Take the
market, and treat this as the shakiest favourite on the board.

**BAL @ BUF — the line assumes Lamar Jackson plays.** High ankle sprain,
three games missed. Wolfson and Rapoport both report he will play;
Minter has not cleared him and says he still did not look himself in
practice. Buffalo -3.5 is the with-Jackson number — without him Buffalo
would be favoured by a touchdown or more. Buffalo either way, and more
safely if he sits.

**BAY @ UCF — Baylor fired its head coach two days ago.** Dave Aranda
out on 25 October at 40-40; Joe Klanderman interim. QB DJ Lagway turned
an ankle against Auburn. Books disagree on the side — Big 12's page has
Baylor -1.5, DocSports has UCF -2.5. A genuine coin flip with a team in
upheaval on one side.

**KSU @ COLO — Kansas State's quarterback room is wrecked.** Avery
Johnson left the Kansas game and missed Arizona State, day-to-day with
neck and shoulder issues. Barnett on crutches, Duff has not played,
Knuth has a tweaked ankle, and a running back has been moved to
quarterback. They are still favoured by 2.5 on the road. The market
knows and has priced it; this is the game most likely to be wrong.

**CHI @ SEA — the 5-2 team is the underdog.** Chicago lost Cole Kmet for
the season, Seattle lost left tackle Charles Cross to a high ankle
sprain. Seattle -3 at home. Worth knowing the records run the other way.

**MIN @ DET — the line is moving toward the dog.** Opened Detroit -4.5,
now -3 to -3.5. Minnesota is unbeaten with Kyler Murray at quarterback
and has struggled on offence anyway. Money coming back to Minnesota is
the kind of movement worth respecting.

**ATL @ TB — FPI is inflating Tampa.** It has the Buccaneers at 69%; the
market says 58%. Tampa is 2-5 and Atlanta's Penix has thrown three
touchdowns in each of the last two weeks, including a win over San
Francisco. Baker Mayfield is back from a dislocated thumb, which is what
the price is paying for. Take the market's number, not the model's.

**LV @ NYJ — a true pick'em.** ESPN lists the Raiders -1.5, Fox lists the
Jets -1.5, and ESPN's own predictor has Las Vegas at 52% while my
reconstruction of FPI has the Jets at 52%. Nobody knows. Pick whichever
you like and do not spend any thought on it.

**WIS @ IOWA — a rock fight.** Total 36.5. Wisconsin's Colton Joseph went
6 of 16 for 66 yards in the loss to UCLA; Iowa will not commit between
Brown and Hecklinski, but Hecklinski won on the road in his first start.
Iowa -3.5 at home in a low-scoring game is sound.

## Where my own numbers were wrong

**CONN @ AFA was a bug, not an insight.** I reported that the data said
UConn and the app said Air Force. Air Force is favoured by 2.5 to 3
everywhere and ESPN's own predictor has them at 61%. The spread was
being read off a printed string and matched against ESPN's spelling of
the home team; when the spelling did not match, the code took the line
for the away side and flipped the sign. Fixed, and it now refuses to
guess rather than guessing wrong.

**Kansas State was not a second instance of that bug.** I said it was.
The source I read wrote the same line from the underdog's side
("Colorado +2.5") and I took it for the opposite. Kansas State -2.5 is
correct and the code had it right.
