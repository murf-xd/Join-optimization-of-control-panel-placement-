# honeywell
Automated electrical panel placement and closed-loop cable routing for the Honeywell 48-hour hackathon
Assumption	----Value----	Why
Open passage minimum width	0.7 m	Just below the narrowest door we measured; sensitivity test pending
Rescue minimum	0.4 m	Used only to reconnect a cut-off eligible room, justified by the benchmark’s reachability guarantee
Gate crossing minimum (MIN_CLEAR_M)	0.2 m	A cable is a line, so a crossing under 20 cm of free space is blocked by a window or wall
Windows are barriers	yes	Statement: cables must not pass windows; slide 3 says windows don’t connect zones
Hub zone clearance from windows	0.5 m	Conservative; the statement only says walls
Balcony	external	Statement lists it as excluded and outside the inner boundary
Bathroom	walkable, no node	Inside the inner boundary, so cables may cross it; contiguity through it is still an open question
Door margin (0.15 × wall_depth, about 3 cm)	small	Bridges the tiny gap between a door polygon and its rooms
