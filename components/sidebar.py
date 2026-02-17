"""
Sidebar Navigation Component for RENA Bot
Replicates Read.ai's complete sidebar menu
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
👤
</div>
<div class="user-name">{user_info['name']}</div>
<div class="user-email">{user_info['email']}</div>
</div>
""", unsafe_allow_html=True)
        
        # Enterprise Badge with Upgrade / Subscription Info
        import meeting_database as db
        profile = db.get_user_profile(user_info['email']) or {}
        plan = profile.get('subscription_plan', 'Free')
        credits = profile.get('credits', 0)
        
        st.markdown(f"""
            <div style="background: rgba(56, 189, 248, 0.1); border: 1px solid rgba(56, 189, 248, 0.2); border-radius: 10px; padding: 12px; margin-bottom: 10px;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-size: 0.8rem; font-weight: 700; color: #38bdf8;">PLAN: {plan.upper()}</span>
                    <span style="font-size: 0.7rem; background: #38bdf8; color: #0f172a; padding: 2px 6px; border-radius: 4px; font-weight: 800;">{credits} CREDITS</span>
                </div>
            </div>
            <div style="display: flex; align-items: center; margin-bottom: 20px; padding: 0 5px;">
                <div class="bot-pulse"></div>
                <span style="font-size: 0.7rem; font-weight: 800; color: #10b981; letter-spacing: 0.05em;">RENA AI: ONLINE</span>
            </div>
        """, unsafe_allow_html=True)

        if plan == 'Free':
            if st.button("🚀 Upgrade to Pro", key="upgrade_btn", use_container_width=True):
                from payment_service import payments
                with st.spinner("Preparing checkout..."):
                    # For demo purposes, we process it locally
                    success, msg = payments.process_simulated_payment(user_info['email'], "pro_monthly")
                    if success:
                        st.success(msg)
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(msg)
        
        st.divider()
        
        # Navigation Menu
        selected_page = current_page
        
        # Main Navigation
        if st.button("👥 Add People", key="nav_add_people", use_container_width=True):
            selected_page = "add_people"
        
        if st.button("🔍 Search Assistant", key="nav_search", use_container_width=True):
            selected_page = "search_assistant"
        
        if st.button("📈 Analytics", key="nav_analytics", use_container_width=True):
            selected_page = "analytics"
            
        if st.button("📄 Reports", key="nav_reports", use_container_width=True):
            selected_page = "reports"
        
        if st.button("🔌 Integrations", key="nav_integrations", use_container_width=True):
            selected_page = "integrations"
            
        if st.button("📁 Folders", key="nav_folders", use_container_width=True):
            selected_page = "folders"
        
        if st.button("📅 Calendar", key="nav_calendar", use_container_width=True):
            selected_page = "calendar"
        
        if st.button("⭐ For You", key="nav_for_you", use_container_width=True):
            selected_page = "for_you"
        
        if st.button("🎯 Coaching", key="nav_coaching", use_container_width=True):
            selected_page = "coaching"
        
        st.divider()
        
        # Workspace Navigation
        st.markdown('<div class="nav-section">Workspaces & Teams</div>', unsafe_allow_html=True)
        import meeting_database as db
        workspaces = db.get_user_workspaces(user_info['email'])
        
        if not workspaces:
            if st.button("➕ Create Workspace", key="nav_create_ws", use_container_width=True):
                selected_page = "add_people"
        else:
            # Active Workspace Selection
            ws_names = [w['name'] for w in workspaces]
            active_ws_name = st.selectbox("Select Workspace", ws_names, index=0, label_visibility="collapsed")
            active_ws = next(w for w in workspaces if w['name'] == active_ws_name)
            st.session_state.active_workspace_id = active_ws['id']
            st.session_state.active_workspace_name = active_ws['name']
            
            if st.button("💬 Workspace Chat", key="nav_ws_chat", use_container_width=True):
                selected_page = "workspace_chat"
            
            if st.button("👥 Manage Members", key="nav_manage_members", use_container_width=True):
                selected_page = "add_people"

        st.divider()
        
        # Quick Actions
        st.markdown('<div class="nav-section">Quick Actions</div>', unsafe_allow_html=True)
        
        if st.button("➕ Add to live meeting", key="nav_live", use_container_width=True):
            selected_page = "add_live"
        
        if st.button("🔗 Smart Scheduler Link", key="nav_scheduler", use_container_width=True):
            selected_page = "scheduler"

        st.divider()
        st.markdown('<div class="nav-section">Account & Support</div>', unsafe_allow_html=True)
        if st.button("⚙️ Profile Settings", key="nav_settings", use_container_width=True):
            selected_page = "settings"
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("📋 Copy link", key="copy_link", use_container_width=True):
                st.toast("Link copied!")
        with col2:
            if st.button("⚙️ Manage", key="manage", use_container_width=True):
                selected_page = "manage"
        
        st.divider()
        
        # Logout
        if st.button("🚪 Logout", key="logout", use_container_width=True):
            if os.path.exists("token.json"):
                os.remove("token.json")
            st.rerun()
        
        return selected_page
