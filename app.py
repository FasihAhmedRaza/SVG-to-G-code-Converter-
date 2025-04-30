import streamlit as st
import svgpathtools
import os
import base64
from svgpathtools import Path
from dotenv import load_dotenv
from openai import OpenAI

# --- Constants ---
GRID_SPACING = 35
DEFAULT_RECESS_DEPTH = 1.75
DEFAULT_EXTRUSION_DEPTH = 0.1
DEFAULT_SCALE_DIVISOR = 100

# Load environment variables
load_dotenv()

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY")) if os.getenv("OPENAI_API_KEY") else None

# --- Core Functions ---
def svg_to_gcode_with_3d_depth_and_colors(svg_file, gcode_file, recess_depth=DEFAULT_RECESS_DEPTH, extrusion_depth=DEFAULT_EXTRUSION_DEPTH, scale_factor=0.05):
    try:
        paths, attributes = svgpathtools.svg2paths(svg_file)
    except Exception as e:
        st.error(f"Error loading SVG file: {e}")
        return

    z_height = 0  # Starting Z height

    def is_point_inside_path(path, x, y):
        point = complex(x, y)
        crossings = 0
        for segment in path:
            if (segment.start.imag > y) != (segment.end.imag > y):
                cross_x = (y - segment.start.imag) * (segment.end.real - segment.start.real) / (segment.end.imag - segment.start.imag) + segment.start.real
                if x < cross_x:
                    crossings += 1
        return crossings % 2 == 1

    def get_bounding_box(path):
        min_x, min_y = float('inf'), float('inf')
        max_x, max_y = float('-inf'), float('-inf')
        for segment in path:
            min_x = min(min_x, segment.start.real, segment.end.real)
            min_y = min(min_y, segment.start.imag, segment.end.imag)
            max_x = max(max_x, segment.start.real, segment.end.real)
            max_y = max(max_y, segment.start.imag, segment.end.imag)
        return min_x, min_y, max_x, max_y

    min_x_all, min_y_all = float('inf'), float('inf')
    max_x_all, max_y_all = float('-inf'), float('-inf')

    for path in paths:
        min_x, min_y, max_x, max_y = get_bounding_box(path)
        min_x_all = min(min_x_all, min_x)
        min_y_all = min(min_y_all, min_y)
        max_x_all = max(max_x_all, max_x)
        max_y_all = max(max_y_all, max_y)

    offset_x = -min_x_all
    offset_y = -min_y_all

    with open(gcode_file, 'w') as gcode:
        gcode.write('; Generated G-code for 3D cutting\n')
        gcode.write('G20 ; Set units to Inches\n')
        gcode.write('G90 ; Use absolute positioning\n')
        gcode.write('G28 ; Home all axes\n')

        for path, attr in zip(paths, attributes):
            color_class = attr.get('class', '')
            
            if 'cls-1' in color_class:  # Light Blue
                local_extrusion_depth = recess_depth / 100
                layer_range = 2

                min_x, min_y, max_x, max_y = get_bounding_box(path)
                current_y = min_y

                while current_y < max_y:
                    x_start = None
                    x_end = None
                    for x in range(int(min_x), int(max_x) + 1):
                        if is_point_inside_path(path, x, current_y):
                            if x_start is None:
                                x_start = x
                            x_end = x
                    if x_start is not None and x_end is not None:
                        gcode.write(f'G1 X{(x_start + offset_x) * scale_factor:.3f} Y{(current_y + offset_y) * scale_factor:.3f} Z{z_height + local_extrusion_depth:.3f} F1500\n')
                        gcode.write(f'G1 X{(x_end + offset_x) * scale_factor:.3f} Y{(current_y + offset_y) * scale_factor:.3f} Z{z_height + local_extrusion_depth:.3f} F1500\n')
                    current_y += GRID_SPACING

            elif 'cls-2' in color_class:  # Dark Blue
                local_extrusion_depth = 0.0
                layer_range = 1
            else:
                local_extrusion_depth = DEFAULT_EXTRUSION_DEPTH
                layer_range = 10

            for layer in range(layer_range):
                for segment in path:
                    start_x = (segment.start.real + offset_x) * scale_factor
                    start_y = (segment.start.imag + offset_y) * scale_factor
                    end_x = (segment.end.real + offset_x) * scale_factor
                    end_y = (segment.end.imag + offset_y) * scale_factor
                    gcode.write(f'G1 X{start_x:.3f} Y{start_y:.3f} Z{z_height:.3f} F1500\n')
                    gcode.write(f'G1 X{end_x:.3f} Y{end_y:.3f} Z{z_height + local_extrusion_depth:.3f} F1500\n')
                z_height -= local_extrusion_depth

        gcode.write('G28 ; Home all axes\n')
        gcode.write('M104 S0 ; Turn off extruder\n')
        gcode.write('M140 S0 ; Turn off bed\n')
        gcode.write('M84 ; Disable motors\n')

# --- AI Functions ---
def get_ai_suggestions(prompt):
    """Get AI suggestions using OpenAI API"""
    if not client:
        st.error("OpenAI client not initialized. Please check your API key.")
        return None
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You're a professional SVG and G-code advisor. Provide concise technical suggestions."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=300
        )
        return response.choices[0].message.content
    except Exception as e:
        st.error(f"Failed to get AI suggestions: {str(e)}")
        return None

# --- UI Functions ---
def get_scale_factor():
    scaling_factor = DEFAULT_SCALE_DIVISOR
    st.subheader("Dimensions Scaling")
    col1, col2 = st.columns(2)
    with col1:
        scaled_width_input = st.number_input("Width in scaled units", min_value=0.0, value=20.0, step=0.1)
    with col2:
        scaled_height_input = st.number_input("Height in scaled units", min_value=0.0, value=40.0, step=0.1)

    width_inch = scaled_width_input / scaling_factor
    height_inch = scaled_height_input / scaling_factor

    scale_factor = min(width_inch, height_inch) / 100
    scale_factor = max(0.001, min(scale_factor, 1.0))
    return scale_factor

# --- Streamlit App ---
def main():
    st.set_page_config(page_title="SVG to G-code Converter", layout="wide")
    
    st.title('SVG to G-code Converter with AI Assist')
    
    # Sidebar for settings and AI options
    with st.sidebar:
        st.header("Settings")
        block_thickness = st.number_input("Block Thickness (inches)", 
                                        min_value=0.1, 
                                        max_value=10.0, 
                                        value=4.0, 
                                        step=0.1)
        
        extrusion_depth_cls_1 = st.number_input("Recess Depth for Light Blue", 
                                              min_value=0.0, 
                                              max_value=block_thickness, 
                                              value=min(1.75, block_thickness), 
                                              step=0.1)
        
        st.header("AI Assistance")
        if client:
            st.success("Connected ")
        else:
            st.warning("OpenAI not available (missing API key)")

    # Main content area
    uploaded_svg = st.file_uploader("Upload SVG File", type="svg")
    
    if uploaded_svg is not None:
        with st.spinner('Processing SVG file...'):
            svg_path = "uploaded_file.svg"
            with open(svg_path, "wb") as f:
                f.write(uploaded_svg.getbuffer())
            
            # Display SVG preview
            st.subheader("Design Preview")
            svg_base64 = base64.b64encode(uploaded_svg.getvalue()).decode()
            st.markdown(f'<embed src="data:image/svg+xml;base64,{svg_base64}" width="600" height="400" type="image/svg+xml">', unsafe_allow_html=True)
            
            # AI Analysis Section
            if client:
                with st.expander("AI Design Advisor"):
                    ai_prompt = st.text_area("Ask AI for SVG/G-code advice:", 
                                           "How can I optimize this design for CNC milling?")
                    
                    if st.button("Get AI Suggestions"):
                        with st.spinner("Getting expert advice..."):
                            suggestions = get_ai_suggestions(ai_prompt)
                            if suggestions:
                                st.success("AI Suggestions:")
                                st.write(suggestions)
            
            # Conversion settings
            st.subheader("Conversion Settings")
            scale_factor = get_scale_factor()
            
            if st.button("Generate G-code File", type="primary"):
                with st.spinner('Generating G-code...'):
                    output_file = "output.lsi"
                    svg_to_gcode_with_3d_depth_and_colors(
                        svg_path, 
                        output_file,
                        recess_depth=extrusion_depth_cls_1,
                        scale_factor=scale_factor
                    )
                    
                    with open(output_file, "rb") as f:
                        st.download_button(
                            "Download G-code File",
                            f,
                            file_name=output_file,
                            mime="text/plain"
                        )
                    st.success("G-code generated successfully!")

if __name__ == "__main__":
    main()