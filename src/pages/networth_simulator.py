import streamlit as st
import numpy as np
import plotly.graph_objs as go
from utils.models import Pot
from datetime import datetime

st.title('Net Worth Simulator')

if 'pots' not in st.session_state:
    st.session_state.pots = []
    
if 'contribution_types' not in st.session_state:
    st.session_state.contribution_types = {}

def add_pot():
    new_pot = Pot(name=f"Pot {len(st.session_state.pots) + 1}")
    st.session_state.pots.append(new_pot)
    st.session_state.contribution_types[new_pot.name] = "Monthly"

def remove_pot(index):
    pot_name = st.session_state.pots[index].name
    del st.session_state.pots[index]
    if pot_name in st.session_state.contribution_types:
        del st.session_state.contribution_types[pot_name]
    st.rerun()

# Display pot inputs
for i, pot in enumerate(st.session_state.pots):
    st.write("###", pot.name)
    input_cols = st.columns([1, 1, 1, 1, 0.2])
    
    with input_cols[0]:
        pot.initial = st.number_input(
            "Initial Amount",
            min_value=0.0,
            value=float(pot.initial) if pot.initial is not None else 0.0,
            key=f"initial_{i}_{pot.name}"
        )
    
    with input_cols[1]:
        contribution_type = st.selectbox(
            "Contribution Type",
            options=["Monthly", "Yearly"],
            index=0 if st.session_state.contribution_types.get(pot.name, "Monthly") == "Monthly" else 1,
            key=f"contribution_type_{i}_{pot.name}"
        )
        st.session_state.contribution_types[pot.name] = contribution_type
    
    with input_cols[2]:
        contribution_label = "Monthly" if contribution_type == "Monthly" else "Yearly"
        pot.monthly = st.number_input(
            f"{contribution_label} Contribution",
            min_value=0.0,
            value=float(pot.monthly) if pot.monthly is not None else 0.0,
            key=f"contribution_{i}_{pot.name}"
        )
    
    with input_cols[3]:
        pot.rate = st.number_input(
            "Annual Return Rate (%)",
            min_value=0.0,
            max_value=100.0,
            value=float(pot.rate) if pot.rate is not None else 0.0,
            key=f"rate_{i}_{pot.name}"
        )
    
    with input_cols[4]:
        st.write("")  # Add some spacing
        st.write("")  # Add some spacing
        if st.button("🗑️", key=f"remove_{i}_{pot.name}", help=f"Remove {pot.name}"):
            remove_pot(i)
    
    st.divider()

col1, col2, col3 = st.columns([1, 1, 1])
with col2:
    st.button('Add Pot', on_click=add_pot, use_container_width=True)

def simulate_net_worth(years=30):
    months = years * 12
    timeline = np.arange(months)
    total_networth = np.zeros(months)
    pot_breakdown = {}
    for pot_item in st.session_state.pots:
        initial = pot_item.initial if pot_item.initial is not None else 0.0
        contribution = pot_item.monthly if pot_item.monthly is not None else 0.0
        # Convert yearly contribution to monthly if needed
        if st.session_state.contribution_types.get(pot_item.name) == "Yearly":
            contribution = contribution / 12
        rate = (pot_item.rate / 100) if pot_item.rate is not None else 0.0
        
        growth = initial * ((1 + rate / 12) ** timeline)
        if rate == 0:
            contributions = contribution * timeline
        else:
            contributions = contribution * (((1 + rate / 12) ** timeline - 1) / (rate / 12))
        networth_for_pot = growth + contributions
        total_networth += networth_for_pot
        pot_breakdown[pot_item.name] = networth_for_pot
    return timeline, total_networth, pot_breakdown

if not st.session_state.pots:
    st.warning("Please add at least one pot to simulate.")
else:
    st.write("### Simulation Settings")
    years = st.slider("Simulation Period (Years)", min_value=1, max_value=50, value=30, key="simulation_years")
    
    # Add pot selection
    selected_pots = st.multiselect(
        "Select Pots to Display",
        options=[pot.name for pot in st.session_state.pots],
        default=[pot.name for pot in st.session_state.pots],
        key="selected_pots"
    )
    
    if selected_pots:
        timeline, networth_result, pot_breakdown = simulate_net_worth(years=years)
        
        filtered_pot_breakdown = {name: data for name, data in pot_breakdown.items() if name in selected_pots}
        filtered_networth = sum(filtered_pot_breakdown.values())
        
        # Total Net Worth Plot
        fig_total = go.Figure()
        fig_total.add_trace(go.Scatter(
            x=timeline / 12, 
            y=filtered_networth, 
            mode='lines', 
            name='Total Net Worth',
            line=dict(color='#2E86AB', width=3),
            fill='tonexty'
        ))
        fig_total.update_layout(
            title=dict(
                text='Total Net Worth Growth Over Time',
                font=dict(size=20, color='#1a1a1a')
            ),
            xaxis_title='Years',
            yaxis_title='Net Worth',
            xaxis=dict(range=[0, years]),
            plot_bgcolor='#f8f9fa',
            paper_bgcolor='white',
            font=dict(color='#333333'),
            margin=dict(l=60, r=60, t=80, b=60)
        )
        st.plotly_chart(fig_total)

        # Pot Breakdown Plot
        fig_breakdown = go.Figure()
        
        # Define a color palette for different pots
        colors = ['#2E86AB', '#A23B72', '#F18F01', '#C73E1D', '#7209B7', '#048A81', '#F77F00', '#FCBF49']
        
        for i, (name, data) in enumerate(filtered_pot_breakdown.items()):
            color = colors[i % len(colors)]
            fig_breakdown.add_trace(go.Scatter(
                x=timeline / 12, 
                y=data, 
                mode='lines', 
                name=name,
                line=dict(color=color, width=2.5),
                fill='tonexty' if i == 0 else None
            ))
        
        fig_breakdown.update_layout(
            title=dict(
                text='Net Worth Breakdown by Pot',
                font=dict(size=20, color='#1a1a1a')
            ),
            xaxis_title='Years',
            yaxis_title='Net Worth',
            showlegend=True,
            xaxis=dict(range=[0, years]),
            plot_bgcolor='#f8f9fa',
            paper_bgcolor='white',
            font=dict(color='#333333'),
            margin=dict(l=60, r=60, t=80, b=60),
            legend=dict(
                bgcolor='rgba(255,255,255,0.8)',
                bordercolor='#cccccc',
                borderwidth=1
            )
        )
        st.plotly_chart(fig_breakdown)

        pot_settings_html = ""
        for pot_item in st.session_state.pots:
            if pot_item.name in selected_pots:
                contribution_type = st.session_state.contribution_types.get(pot_item.name, "Monthly")
                contribution_label = "Monthly" if contribution_type == "Monthly" else "Yearly"
                pot_settings_html += f"""\
                <div class="pot-card">
                    <h4>{pot_item.name}</h4>
                    <ul>
                        <li><strong>Initial Amount:</strong> £{pot_item.initial if pot_item.initial is not None else 0.0:,.2f}</li>
                        <li><strong>{contribution_label} Contribution:</strong> £{pot_item.monthly if pot_item.monthly is not None else 0.0:,.2f}</li>
                        <li><strong>Annual Return Rate:</strong> {pot_item.rate if pot_item.rate is not None else 0.0:.2f}%</li>
                    </ul>
                </div>
                """

        html_report = f"""\
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Net Worth Simulation Report</title>
            <style>
                * {{
                    margin: 0;
                    padding: 0;
                    box-sizing: border-box;
                }}
                
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh;
                    padding: 20px;
                }}
                
                .container {{
                    max-width: 1200px;
                    margin: 0 auto;
                    background: white;
                    border-radius: 15px;
                    box-shadow: 0 20px 40px rgba(0,0,0,0.1);
                    overflow: hidden;
                }}
                
                .header {{
                    background: linear-gradient(135deg, #2E86AB 0%, #A23B72 100%);
                    color: white;
                    padding: 40px;
                    text-align: center;
                }}
                
                .header h1 {{
                    font-size: 2.5em;
                    margin-bottom: 10px;
                    font-weight: 300;
                }}
                
                .header p {{
                    font-size: 1.2em;
                    opacity: 0.9;
                }}
                
                .content {{
                    padding: 40px;
                }}
                
                .section {{
                    margin-bottom: 40px;
                    padding: 30px;
                    background: #f8f9fa;
                    border-radius: 10px;
                    border-left: 5px solid #2E86AB;
                }}
                
                .section h2 {{
                    color: #2E86AB;
                    font-size: 1.8em;
                    margin-bottom: 20px;
                    font-weight: 500;
                }}
                
                .section h3 {{
                    color: #A23B72;
                    font-size: 1.4em;
                    margin-bottom: 15px;
                    font-weight: 500;
                }}
                
                .section h4 {{
                    color: #333;
                    font-size: 1.2em;
                    margin-bottom: 10px;
                    font-weight: 500;
                }}
                
                .settings-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                    gap: 20px;
                    margin-top: 20px;
                }}
                
                .pot-card {{
                    background: white;
                    padding: 20px;
                    border-radius: 8px;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.05);
                    border-left: 4px solid #2E86AB;
                }}
                
                .pot-card h4 {{
                    color: #2E86AB;
                    margin-bottom: 15px;
                }}
                
                .pot-card ul {{
                    list-style: none;
                }}
                
                .pot-card li {{
                    padding: 8px 0;
                    border-bottom: 1px solid #eee;
                    display: flex;
                    justify-content: space-between;
                }}
                
                .pot-card li:last-child {{
                    border-bottom: none;
                }}
                
                .pot-card li strong {{
                    color: #A23B72;
                }}
                
                .chart-container {{
                    background: white;
                    padding: 20px;
                    border-radius: 10px;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.05);
                    margin: 20px 0;
                }}
                
                .summary-stats {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                    gap: 20px;
                    margin: 20px 0;
                }}
                
                .stat-card {{
                    background: linear-gradient(135deg, #2E86AB, #A23B72);
                    color: white;
                    padding: 20px;
                    border-radius: 10px;
                    text-align: center;
                }}
                
                .stat-card h3 {{
                    font-size: 2em;
                    margin-bottom: 5px;
                }}
                
                .stat-card p {{
                    opacity: 0.9;
                }}
                
                @media (max-width: 768px) {{
                    .container {{
                        margin: 10px;
                        border-radius: 10px;
                    }}
                    
                    .header {{
                        padding: 20px;
                    }}
                    
                    .header h1 {{
                        font-size: 2em;
                    }}
                    
                    .content {{
                        padding: 20px;
                    }}
                    
                    .section {{
                        padding: 20px;
                    }}
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>📈 Net Worth Simulation Report</h1>
                    <p>Generated on {datetime.now().strftime('%B %d, %Y at %I:%M %p')}</p>
                </div>
                
                <div class="content">
                    <div class="section">
                        <h2>📊 Simulation Overview</h2>
                        <div class="summary-stats">
                            <div class="stat-card">
                                <h3>{years}</h3>
                                <p>Years Simulated</p>
                            </div>
                            <div class="stat-card">
                                <h3>{len(selected_pots)}</h3>
                                <p>Investment Pots</p>
                            </div>
                            <div class="stat-card">
                                <h3>£{filtered_networth[-1]:,.0f}</h3>
                                <p>Final Net Worth</p>
                            </div>
                        </div>
                    </div>
                    
                    <div class="section">
                        <h2>📋 Selected Pots</h2>
                        <p><strong>Active Pots:</strong> {', '.join(selected_pots)}</p>
                    </div>
                    
                    <div class="section">
                        <h2>💰 Pot Configuration</h2>
                        <div class="settings-grid">
                            {pot_settings_html}
                        </div>
                    </div>
                    
                    <div class="section">
                        <h2>📈 Total Net Worth Growth</h2>
                        <div class="chart-container">
                            {fig_total.to_html(full_html=False, include_plotlyjs='cdn')}
                        </div>
                    </div>
                    
                    <div class="section">
                        <h2>🎯 Pot Breakdown Analysis</h2>
                        <div class="chart-container">
                            {fig_breakdown.to_html(full_html=False, include_plotlyjs='cdn')}
                        </div>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
        st.download_button(
            label="Save Report as HTML",
            data=html_report,
            file_name="net_worth_report.html",
            mime="text/html"
        )
    else:
        st.warning("Please select at least one pot to display the simulation results.")
