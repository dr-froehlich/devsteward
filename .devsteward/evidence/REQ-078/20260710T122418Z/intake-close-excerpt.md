committing it serializes id allocation and keeps the index/roadmap consistent.

**Close by naming the next command precisely (REQ-078).** When you suggest starting
development, phrase it as **`/advance REQ-NNN develop`** naming *this* just-intook REQ —
never a bare "run advance". A bare suggestion lets `/advance` self-orient onto whatever
step the cursor happens to make eligible (often an unrelated pending validation); an
explicit target can only ever start the REQ you just wrote.
