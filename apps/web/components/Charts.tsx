"use client";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

const axis = { stroke: "#8b98a8", fontSize: 10 } as const;

export function TrajectoryChart({ data }: { data: { period: string; revenue: number | null; ebitda: number | null; margin: number | null }[] }) {
  return (
    <div className="grid grid-cols-2 gap-3">
      <div className="h-48">
        <ResponsiveContainer><BarChart data={data}><CartesianGrid stroke="#222b36" /><XAxis dataKey="period" {...axis} /><YAxis {...axis} /><Tooltip contentStyle={{ background: "#11161d", border: "1px solid #2d3947" }} /><Bar dataKey="revenue" fill="#38bdf8" name="Revenue ₹cr" /><Bar dataKey="ebitda" fill="#3ddc97" name="EBITDA ₹cr" /></BarChart></ResponsiveContainer>
      </div>
      <div className="h-48">
        <ResponsiveContainer><LineChart data={data}><CartesianGrid stroke="#222b36" /><XAxis dataKey="period" {...axis} /><YAxis {...axis} tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`} /><Tooltip contentStyle={{ background: "#11161d", border: "1px solid #2d3947" }} formatter={(v: number) => `${(v * 100).toFixed(1)}%`} /><Line type="monotone" dataKey="margin" stroke="#ffc857" dot={false} name="EBITDA margin" /></LineChart></ResponsiveContainer>
      </div>
    </div>
  );
}

export function SeriesChart({ data, keys, percent = false }: { data: Record<string, number | string | null>[]; keys: { key: string; color: string; label: string }[]; percent?: boolean }) {
  return (
    <div className="h-48">
      <ResponsiveContainer>
        <LineChart data={data}>
          <CartesianGrid stroke="#222b36" /><XAxis dataKey="x" {...axis} /><YAxis {...axis} tickFormatter={(v: number) => (percent ? `${v.toFixed(0)}%` : v.toFixed(0))} />
          <Tooltip contentStyle={{ background: "#11161d", border: "1px solid #2d3947" }} />
          {keys.map((k) => <Line key={k.key} type="monotone" dataKey={k.key} stroke={k.color} dot={false} name={k.label} />)}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function DecayChart({ data }: { data: { horizon: string; mean_excess: number | null }[] }) {
  return (
    <div className="h-24 w-56">
      <ResponsiveContainer><LineChart data={data}><XAxis dataKey="horizon" {...axis} /><YAxis {...axis} tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`} /><Line type="monotone" dataKey="mean_excess" stroke="#3ddc97" dot /></LineChart></ResponsiveContainer>
    </div>
  );
}
