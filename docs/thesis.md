# The thesis

The durable idea this repo was one instantiation of. Written at mothball, 2026-09-17,
because the product was specific to X and the idea is not.

## The observation

**Platforms hide hostile inbound media. They do not act on the sender.**

This was checked, not assumed. X ships a graphic-media filter in DMs that is on by
default, hides media in message requests, and routes suspect senders to the bottom of a
Requests tab. It works. And it leaves the user with exactly the same job: open the
request, look, decide, block. X's own help centre lists three ways to stop a sender —
Block, DM block, Report — and all three are manual, one sender at a time, after the
fact. Deleting a request does not even prevent the sender from messaging again.

So the labour is not *seeing* the content. It is **triage and enforcement**, and it is
unbounded, because hiding does not remove the sender.

The client this repo was built for did not ask for a better filter. They asked to stop
spending an hour a day opening requests and clicking Block.

## Why platforms will not close this

A hide is reversible and private. A block mutates the user's social graph, is visible to
the other party, and is wrong in a way the user feels. A platform that auto-blocks on a
false positive has silently damaged a relationship on the user's behalf, at a scale where
even a 0.1% error rate is a support catastrophe.

So platforms stop at "we hid it, you decide." That boundary is structural, not a gap in
their models, and it does not close with a better classifier. **It is the durable
opening.**

## What generalizes

Nothing above is about X. It holds wherever strangers can attach media to an inbox the
recipient cannot close:

Discord DMs and mod queues · Twitch whispers · Instagram message requests · Bluesky ·
Patreon and Substack inboxes · community platforms with any open contact surface

The buyer is the same everywhere: someone who takes real volume, cannot simply close
their inbox, and either triages at a desk or pays someone else to. Creators,
journalists, public figures, trust-and-safety teams. It has never been a consumer play —
the per-item cost floor kills that on any platform that meters its API.

## What a solution actually needs

Four things, in order of how often they get skipped:

1. **A verdict with granularity.** Not "sensitive" — a category, so the policy can be
   "block on graphic violence, never on nudity." A blur is not an actionable verdict.
2. **An action.** Block, mute, restrict, or quarantine. Without this it is another
   filter, and filters already exist for free.
3. **An audit trail and an undo.** You are mutating someone's social graph from
   infrastructure they do not control. Every decision needs a row, a reason, and a way
   back.
4. **Explicit consent for the action, separate from sign-in.** X's Developer Policy says
   it outright: "a person authenticating into your service does not by itself constitute
   consent." That is good policy regardless of platform.

## What X taught us about picking a host platform

X was a bad first host, and the reasons are a checklist for the next one:

- **Metered ingress.** ~$0.02–0.03 per moderated media DM. COGS scales with abuse, so the
  customers who need it most cost the most to serve.
- **Unstable pricing.** Block Party — a funded startup in exactly this category — went on
  hiatus in 2023 when Twitter paywalled the API. Block Together and MegaBlock died the
  same way. None failed for lack of demand.
- **An encryption roadmap that ends the category.** X files `dm.received` under "legacy,
  unencrypted DM events" beside a parallel encrypted set. Server-side classification of
  end-to-end encrypted media is not hard, it is impossible.

Evaluate the next platform on: is ingress free or metered, has pricing been stable, is
there an enforcement API a third party may call on a user's behalf, and is the message
surface heading toward E2E encryption.

## What is worth carrying forward

Not the job queue. Not the ingress. Those are a week's work in any language.

- **The classification policy** — a single named harm category, frames sampled at 1fps
  from t=1s capped at 12s, block if any frame trips. 422 lines in
  `dmguard/moderator.py` and `dmguard/classifier_llavaguard.py`.
- **The finding that the gap is enforcement, not detection.** That is the whole idea, and
  it took an audit to see clearly.
- **The architectural hedge:** if a platform's messages may go end-to-end encrypted, the
  classifier must stay callable from a client-side context. A hosted-only design cannot
  follow the data.
