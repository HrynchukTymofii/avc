"use client";

import { useState } from "react";
import { BookOpenIcon, CheckIcon, CopyIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

const AI_PROMPT = `Write a voice-over narration script about [TOPIC], about [DURATION] long when read aloud at a natural pace (~150 words per minute).

Rules for the script:
- Plain spoken text only — no headings, no stage directions, no markdown, no emojis.
- Short sentences. One idea per sentence. Conversational, like talking to one person.
- Write out every number, unit, date and abbreviation the way it should be spoken ("twenty five percent", not "25%").
- End sentences with normal punctuation. Use commas for short pauses and "..." for a hesitation.
- You may insert [pause] for a beat of silence, or [pause:2] for a two-second silence, between thoughts.
- No intro like "Here's the script" — output the narration text only.`;

/** The marks the narration engine actually honors. [pause] markers are cut out
 * of the text and replaced with real silence; punctuation drives the delivery
 * of everything else. */
const PACING_MARKS: { mark: string; effect: string }[] = [
  { mark: "[pause]", effect: "a beat of silence (0.6 s) — the marker is never spoken" },
  { mark: "[pause:2]", effect: "exactly that many seconds of silence (up to 10)" },
  { mark: ",", effect: "short pause inside a sentence" },
  { mark: ". ! ?", effect: "full stop — ends the phrase with matching intonation" },
  { mark: "…", effect: "hesitation / trailing off" },
  { mark: "New sentence", effect: "a brief natural gap between sentence groups" },
];

const TONE_MARKS: { mark: string; effect: string }[] = [
  { mark: "(excited)", effect: "brighter, faster delivery of the following text" },
  { mark: "(sad)", effect: "slower, lower delivery" },
  { mark: "(whispering)", effect: "hushed delivery" },
  { mark: "(laughing)", effect: "adds a laugh" },
];

export function VoiceGuideDialog() {
  const [copied, setCopied] = useState(false);

  const copyPrompt = async () => {
    try {
      await navigator.clipboard.writeText(AI_PROMPT);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard unavailable (http) — the user can still select the text
    }
  };

  return (
    <Dialog>
      <DialogTrigger
        render={
          <Button variant="outline" size="sm">
            <BookOpenIcon className="size-3.5" />
            How to write your script
          </Button>
        }
      />
      <DialogContent className="max-w-xl">
        <div className="max-h-[75vh] space-y-6 overflow-y-auto pr-2">
          <div className="pr-6">
            <DialogTitle>Writing a great narration script</DialogTitle>
            <p className="mt-1 text-sm text-muted-foreground">
              The voice clone reads your script exactly as written — punctuation
              is how you direct it.
            </p>
          </div>

          <section className="space-y-2">
            <h3 className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
              Pacing marks
            </h3>
            <div className="overflow-hidden rounded-xl border">
              {PACING_MARKS.map((row) => (
                <div
                  key={row.mark}
                  className="flex items-start gap-4 border-b px-4 py-2.5 text-sm last:border-b-0"
                >
                  <code className="w-28 shrink-0 font-mono text-xs text-primary">
                    {row.mark}
                  </code>
                  <span className="text-foreground/85">{row.effect}</span>
                </div>
              ))}
            </div>
          </section>

          <section className="space-y-2">
            <h3 className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
              Tone markers <span className="normal-case">· experimental</span>
            </h3>
            <p className="text-xs text-muted-foreground">
              Put a marker in parentheses right before the text it should color.
              Results vary by voice — generate a short test first.
            </p>
            <div className="overflow-hidden rounded-xl border">
              {TONE_MARKS.map((row) => (
                <div
                  key={row.mark}
                  className="flex items-start gap-4 border-b px-4 py-2.5 text-sm last:border-b-0"
                >
                  <code className="w-28 shrink-0 font-mono text-xs text-primary">
                    {row.mark}
                  </code>
                  <span className="text-foreground/85">{row.effect}</span>
                </div>
              ))}
            </div>
          </section>

          <section className="space-y-2">
            <h3 className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
              Tips that make the biggest difference
            </h3>
            <ul className="list-disc space-y-1.5 pl-5 text-sm text-foreground/85">
              <li>Write out numbers, dates and units as words — the voice reads literally.</li>
              <li>Short sentences sound natural; very long ones rush.</li>
              <li>Read it aloud once yourself — if you stumble, the voice will too.</li>
              <li>One minute of narration is roughly 150 words (900 characters).</li>
            </ul>
          </section>

          <section className="space-y-2">
            <h3 className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
              Let an AI write it for you
            </h3>
            <p className="text-xs text-muted-foreground">
              Paste this into ChatGPT or Claude, fill in the topic and duration,
              then paste the result into the script editor.
            </p>
            <div className="relative rounded-xl bg-secondary/50 p-4">
              <pre className="whitespace-pre-wrap font-mono text-xs leading-relaxed text-foreground/85">
                {AI_PROMPT}
              </pre>
              <Button
                size="sm"
                variant="secondary"
                onClick={copyPrompt}
                className="absolute right-3 top-3"
              >
                {copied ? <CheckIcon className="size-3.5" /> : <CopyIcon className="size-3.5" />}
                {copied ? "Copied" : "Copy"}
              </Button>
            </div>
          </section>
        </div>
      </DialogContent>
    </Dialog>
  );
}
