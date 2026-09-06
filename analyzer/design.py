"""Presentation-only components for the investment workspace."""
from html import escape
from pathlib import Path

import streamlit as st


def apply_theme():
    st.html("<style>" + Path(__file__).with_name("theme.css").read_text() + "</style>")


def section(number, title, description=""):
    st.html(f'<div class="section-label"><span>{escape(number)}</span><div><h3>{escape(title)}</h3>'
            f'<p>{escape(description)}</p></div></div>')


def wordmark():
    st.html('<div class="wordmark"><span class="brand-mark">↗</span><span>invest<span class="brand-period">.</span></span></div>'
            '<div class="workspace-label">PERSONAL WORKSPACE</div>')


def method_panel():
    st.html('''<aside class="method-panel">
      <div class="eyebrow">THE INVESTMENT FILTER</div>
      <h2>Two paths.<br> One clear decision.</h2>
      <p class="method-intro">Every opportunity has to earn its place through one of two cases.</p>
      <div class="path-block"><div class="path-symbol">↗</div>
        <div class="path-title">100× potential</div>
        <p>A credible path to an exceptional return, after dilution and fees.</p>
        <span class="path-note">UPSIDE THAT JUSTIFIES THE RISK</span></div>
      <div class="path-block"><div class="path-symbol">◇</div>
        <div class="path-title">Downside protection</div>
        <p>Durable fundamentals and a price that supports capital preservation.</p>
        <span class="path-note">EVIDENCE OVER REPUTATION</span></div>
      <div class="method-footer"><span class="tiny-dot"></span> Invest or pass. Always with a reason.</div>
    </aside>
    <div class="workflow-note"><span>01 &nbsp; Read the evidence</span><span>02 &nbsp; Test the return case</span><span>03 &nbsp; Get your decision</span></div>''')


def breadcrumb(active=False):
    st.html('<div class="topbar"><div>Workspace <span>/</span> Investments <span>/</span> '
            + ('<b>Analysis</b>' if active else '<b>New analysis</b>')
            + '</div><div class="private-label"><span class="tiny-dot"></span> Private workspace</div></div>')


def storage_badge(cloud):
    st.html('<div class="storage-badge"><span class="tiny-dot"></span>'
            + ('Private cloud' if cloud else 'Local workspace')
            + '<small>' + ('Only your account has access' if cloud else 'Saved on this computer') + '</small></div>')
