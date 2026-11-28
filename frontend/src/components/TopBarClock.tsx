import { useEffect, useState } from "react";

const TZ = "Asia/Bangkok";
const TICK_MS = 60_000;

export function formatBangkokClock(now: Date): { date: string; time: string } {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: TZ,
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(now);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  const beYear = Number(get("year")) + 543;
  return {
    date: `${get("day")}/${get("month")}/${beYear}`,
    time: `${get("hour")}:${get("minute")}`,
  };
}

export function TopBarClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    let interval: ReturnType<typeof setInterval> | undefined;
    // Align to the next minute boundary, then tick every 60 s.
    const timeout = setTimeout(() => {
      setNow(new Date());
      interval = setInterval(() => setNow(new Date()), TICK_MS);
    }, TICK_MS - (Date.now() % TICK_MS));
    return () => {
      clearTimeout(timeout);
      if (interval) clearInterval(interval);
    };
  }, []);
  const { date, time } = formatBangkokClock(now);
  return (
    <time
      data-testid="top-bar-clock"
      dateTime={now.toISOString()}
      className="whitespace-nowrap text-xs tabular-nums text-[var(--text-muted)]"
    >
      <span className="hidden sm:inline" data-testid="clock-date">
        {date}{" "}
      </span>
      <span data-testid="clock-time">{time}</span>
    </time>
  );
}
