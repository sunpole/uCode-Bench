"""One main Tests tab; old page-selection calls remain compatible."""
from tkinter import ttk


class HubNotebook(ttk.Notebook):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs); self.tests=None; self.container=None

    def test_hub(self,container):
        self.container=container
        self.tests=ttk.Notebook(container,style="Tests.TNotebook")
        self.tests.pack(fill="both",expand=True)
        self.tests.bind("<<NotebookTabChanged>>",lambda event:self.event_generate("<<NotebookTabChanged>>"),add="+")
        return self.tests

    def select(self,tab_id=None):
        if self.tests is None: return super().select(tab_id)
        if tab_id is not None and str(tab_id) in self.tests.tabs():
            super().select(self.container); self.tests.select(tab_id); return None
        selected=super().select(tab_id)
        return self.tests.select() if tab_id is None and selected==str(self.container) else selected


def from_controls(app,kind):
    from .test_commands import TestCommand
    if kind=="lab":
        from .lab_ui import read_form
        from .test_controls import custom_config
        config=read_form(app) if app.test_controls.expanded else custom_config(app)
    elif kind=="pipeline": config=app.pipeline_view.config()
    elif kind=="search": config=app.search_view.config()
    elif kind=="scientific":
        from .test_commands import MERGERS
        config={"size":"all" if app.scientific_size.get()=="all" else int(app.scientific_size.get()),"methods":tuple(app.selected_engines) if app.selected_engines is not None else tuple(MERGERS.values())}
    else: raise ValueError("Выберите страницу параметров теста")
    return TestCommand(kind,config)


def apply_to_controls(app,command):
    from dataclasses import replace
    from .print_settings import PrintSettings
    from .ui_layout import QA_MODES,PDF_PROFILES
    from .lab_ui import UNITS
    c=command.config
    if command.kind=="scientific":
        app.scientific_size.set(str(c["size"])); app.selected_engines=list(c["methods"]); app.qa_mode_var.set("Полная")
        for name,var in getattr(app,"_performance_options",[]): var.set(name in c["methods"])
        app.notebook.select(app.pages["tests"]); return
    app.print_settings=PrintSettings(**c.print_settings)
    app.xy_mode_var.set(c.timeline_mode)
    app.pdf_profile_var.set(next(label for label,value in PDF_PROFILES.items() if value==app.print_settings.pdf_profile))
    app.qa_mode_var.set(next(label for label,value in QA_MODES.items() if value==c.qa_mode))
    app.geometry_basis.set("side"); app.geometry_value.set(f"{app.print_settings.side_mm:g}"); app.quiet_var.set(str(app.print_settings.quiet_modules))
    for var,value in zip(app.ink_vars,app.print_settings.ink): var.set(f"{value:g}")
    def put(variable,value): variable.set(",".join(map(str,value)) if isinstance(value,tuple) else str(value))
    if command.kind=="lab":
        if not app.test_controls.expanded: app.test_controls.toggle()
        app.lab_units.set(next(label for label,value in UNITS.items() if set(value)==set(c.cpu_units)))
        for var,value in ((app.lab_counts,c.counts),(app.lab_cpus,c.cpu_counts),(app.lab_backends,c.backends),(app.lab_ram,c.ram_modes),(app.lab_repeats,c.repeats),(app.lab_warmups,c.warmups),(app.lab_batch,c.batch_size),(app.lab_workers,c.workers),(app.lab_pdf_profiles,c.pdf_profiles),(app.lab_activities,c.activity_modes),(app.lab_telemetry,c.telemetry_modes),(app.mode_var,c.output_mode)): put(var,value)
        app.lab_refresh()
    else:
        view=app.pipeline_view if command.kind=="pipeline" else app.search_view
        mapping=((view.counts,c.counts),(view.repeats,c.repeats),(view.ram,c.ram_mode))
        for var,value in mapping: put(var,value)
        if command.kind=="pipeline":
            for var,value in ((view.allocations,c.allocations),(view.schedules,c.schedules),(view.batches,c.batches),(view.telemetry,c.telemetry_modes),(view.processes,c.processes_per_cpu)): put(var,value)
            from .pipeline_plan import allocation_label
            view.options=list(dict.fromkeys(view.options+list(c.allocations))); view.alloc_picker.set_options([(allocation_label(v),v) for v in view.options])
        else:
            for var,value in ((view.units,c.cpu_units),(view.methods,c.backends),(view.pdf,c.pdf_profiles),(view.activities,c.activities),(view.batches,c.batches),(view.parts,c.part_counts),(view.part_modes,c.part_modes),(view.mergers,c.mergers),(view.mode,c.search_mode),(view.best,c.keep_best),(view.telemetry,c.telemetry_mode),(view.cpu_counts,c.cpu_counts)): put(var,value)
            view.all_cpus.set(c.all_cpu_counts)
        view.refresh()
    app.update_geometry(); app.remember(); app.notebook.select(app.pages[command.kind])
