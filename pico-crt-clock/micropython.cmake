# micropython.cmake
# Place this file next to mod_gfx.c / gfx_core1.c / gfx_queue.h
# in your module directory, e.g.:
#
#   my_modules/
#     gfx_queue.h
#     gfx_core1.c
#     mod_gfx.c
#     micropython.cmake
#
# Build with:
#   cd micropython/ports/rp2
#   make BOARD=PICO USER_C_MODULES=/absolute/path/to/my_modules/micropython.cmake
#
# (USER_C_MODULES must be an absolute path pointing directly at this .cmake file)

add_library(usermod_gfx INTERFACE)

target_sources(usermod_gfx INTERFACE
    # Our files
    ${CMAKE_CURRENT_LIST_DIR}/mod_gfx.c
    ${CMAKE_CURRENT_LIST_DIR}/gfx_core1.c

    # cvideo.c is patched in-tree by build.sh before cmake runs (patch applied
    # from patches/pico-mposite.patch, reverted on exit).
    ${CMAKE_CURRENT_LIST_DIR}/../pico-mposite/cvideo.c
    ${CMAKE_CURRENT_LIST_DIR}/../pico-mposite/graphics.c
    ${CMAKE_CURRENT_LIST_DIR}/../pico-mposite/bitmap.c
    ${CMAKE_CURRENT_LIST_DIR}/../pico-mposite/charset.c
    ${CMAKE_CURRENT_LIST_DIR}/../pico-mposite/terminal.c
)

target_include_directories(usermod_gfx INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}
    ${CMAKE_CURRENT_LIST_DIR}/../pico-mposite
)

# pico-mposite needs these SDK components
target_link_libraries(usermod_gfx INTERFACE
    pico_multicore
    hardware_pio
    hardware_dma
    hardware_irq
)

# pico-mposite has some unused/uninitialized variable warnings; suppress them
# without touching the upstream source.
set_source_files_properties(
    ${CMAKE_CURRENT_LIST_DIR}/../pico-mposite/graphics.c
    PROPERTIES COMPILE_OPTIONS "-Wno-unused-variable;-Wno-maybe-uninitialized"
)

# Wire into the MicroPython usermod target
target_link_libraries(usermod INTERFACE usermod_gfx)
