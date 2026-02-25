"""
Sidebar Navigation Component for Renata Bot
Handles page routing and user info display
"""
import streamlit as st
import textwrap
import time
import os
import sys
import subprocess

def render_sidebar(user_info, current_page="calendar"):
    """
    Render the complete Read.ai-style sidebar navigation
    
    Args:
        user_info: User profile information
        current_page: Currently active page
    
    Returns:
        selected_page: The page user navigated to
    """
    
    with st.sidebar:
        # User Account Section (already implemented)
        st.markdown(textwrap.dedent("""
            <style>
                .user-account {
                    background: rgba(255, 255, 255, 0.05);
                    backdrop-filter: blur(10px);
                    padding: 20px;
                    border-radius: 15px;
                    margin-bottom: 20px;
                    text-align: center;
                    color: white;
                    border: 1px solid rgba(255, 255, 255, 0.1);
                }
                .user-avatar {
                    width: 70px;
                    height: 70px;
                    border-radius: 50%;
                    border: 2px solid #38bdf8;
                    margin: 0 auto 12px;
                    display: block;
                }
                .user-name {
                    font-size: 1.1rem;
                    font-weight: 700;
                    margin: 8px 0 4px 0;
                    color: #f1f5f9;
                }
                .user-email {
                    font-size: 0.8rem;
                    opacity: 0.7;
                    word-break: break-all;
                    color: #cbd5e1;
                }
                .nav-section {
                    margin: 25px 0 12px 0;
                    font-size: 0.75rem;
                    font-weight: 800;
                    text-transform: uppercase;
                    color: #94a3b8;
                    padding: 0 16px;
                    letter-spacing: 0.05em;
                }
                .bot-pulse {
                    display: inline-block;
                    width: 10px;
                    height: 10px;
                    background: #10b981;
                    border-radius: 50%;
                    margin-right: 8px;
                    box-shadow: 0 0 0 rgba(16, 185, 129, 0.4);
                    animation: pulse-ring 2s infinite;
                }
                @keyframes pulse-ring {
                    0% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
                    70% { box-shadow: 0 0 0 10px rgba(16, 185, 129, 0); }
                    100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
                }
                .sidebar-status {
                    display: flex;
                    align-items: center;
                    padding: 10px 16px;
                    font-size: 0.9rem;
                    color: #a78bfa; /* A nice purple for active status */
                    margin-top: 10px;
                    margin-bottom: 10px;
                }
                .status-dot {
                    display: inline-block;
                    width: 10px;
                    height: 10px;
                    background-color: #10b981; /* Green for active */
                    border-radius: 50%;
                    margin-right: 8px;
                    box-shadow: 0 0 0 rgba(16, 185, 129, 0.4);
                    animation: pulse-status 1.5s infinite;
                }
                @keyframes pulse-status {
                    0% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
                    70% { box-shadow: 0 0 0 8px rgba(16, 185, 129, 0); }
                    100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
                }
            </style>
        """), unsafe_allow_html=True)
        
        # Display user account
        if user_info:
            import base64
            from pathlib import Path
            
            # Resolve image source (handle local paths for uploaded photos)
            img_src = user_info.get('picture')
            if img_src and Path(img_src).exists():
                try:
                    with open(img_src, "rb") as f:
                        encoded = base64.b64encode(f.read()).decode()
                        img_src = f"data:image/png;base64,{encoded}"
                except: pass
            
            if img_src:
                st.markdown(f"""
<div class="user-account">
<img src="{img_src}" class="user-avatar" alt="Profile">
<div class="user-name">{user_info['name']}</div>
<div class="user-email">{user_info['email']}</div>
</div>
""", unsafe_allow_html=True)
            else:
                st.markdown(f"""
<div class="user-account">
<div style="width: 70px; height: 70px; border-radius: 50%; background: rgba(255,255,255,0.3); margin: 0 auto 12px; display: flex; align-items: center; justify-content: center; font-size: 2rem;">
(USER)
</div>
<div class="user-name">{user_info['name']}</div>
<div class="user-email">{user_info['email']}</div>
</div>
""", unsafe_allow_html=True)
        
        st.divider()
        
        # Navigation Menu
        selected_page = current_page
        
        # Main Navigation
        if st.button("Calendar", key="nav_calendar", use_container_width=True):
            selected_page = "calendar"

        if st.button("Add People", key="nav_add_people", use_container_width=True):
            selected_page = "add_people"
        
        if st.button("Search Assistant", key="nav_search", use_container_width=True):
            selected_page = "search_assistant"
        
        if st.button("Analytics", key="nav_analytics", use_container_width=True):
            selected_page = "analytics"
            
        if st.button("Reports / History", key="nav_reports", use_container_width=True):
            selected_page = "reports"
        
        if st.button("Integrations", key="nav_integrations", use_container_width=True):
            selected_page = "integrations"
        
        st.divider()

        # Workspace Navigation (Restored)
        import meeting_database as db
        workspaces = db.get_user_workspaces(user_info['email'])
        
        # Bot Status Indicator
        st.markdown('<div class="sidebar-status">', unsafe_allow_html=True)
        st.markdown('<span class="status-dot"></span> Renata AI: Active', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown('<div class="nav-section">Workspaces & Teams</div>', unsafe_allow_html=True)
        
        if not workspaces:
            if st.button("Create/Join Workspace", key="nav_ws_none", use_container_width=True):
                selected_page = "add_people"
        else:
            # Selector for active workspace
            ws_names = [w['name'] for w in workspaces]
            current_ws_id = st.session_state.get('active_workspace_id')
            active_index = 0
            if current_ws_id:
                for i, w in enumerate(workspaces):
                    if w['id'] == current_ws_id:
                        active_index = i
                        break
            
            selected_ws_name = st.selectbox("Select Workspace", ws_names, index=active_index, label_visibility="collapsed")
            selected_ws = next(w for w in workspaces if w['name'] == selected_ws_name)
            
            # Update session state if changed
            if st.session_state.get('active_workspace_id') != selected_ws['id']:
                st.session_state.active_workspace_id = selected_ws['id']
                st.session_state.active_workspace_name = selected_ws['name']
                st.rerun()

            if st.button("Manage Workspace", key="nav_ws_manage", use_container_width=True):
                selected_page = "add_people"
            
            if st.button("Workspace Chat", key="nav_ws_chat", use_container_width=True):
                selected_page = "workspace_chat"
        
        st.divider()
        
        # Quick Actions
        st.markdown('<div class="nav-section">Quick Actions</div>', unsafe_allow_html=True)
        
        if st.button("Add to live meeting", key="nav_live", use_container_width=True):
            selected_page = "add_live"

        st.divider()
        st.markdown('<div class="nav-section">Account & Support</div>', unsafe_allow_html=True)
        if st.button("Profile Settings", key="nav_settings", use_container_width=True):
            selected_page = "settings"
        
        st.divider()
        
        # Logout
        if st.button("Logout", key="logout", use_container_width=True):
            if os.path.exists("token.json"):
                os.remove("token.json")
            st.rerun()
        
        return selected_page
