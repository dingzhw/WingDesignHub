# WingDesignHub independent file adapter to CCBlade.jl 1.0.0 (MIT, Andrew Ning).
# Uses the official Rotor/Section/solve/thrusttorque interfaces without modifying CCBlade.
using CCBlade
using TOML
using SHA

function main(input_path, output_path)
    request=TOML.parsefile(input_path)
    Base.pkgversion(CCBlade)==v"1.0.0" || error("CCBlade 1.0.0 required")
    official=get(request,"official",false)
    if official
        af=AlphaAF(request["airfoil_path"])
        radial=Float64.(request["radial_fraction"])
        chord=Float64.(request["chord_m"])
        twist=Float64.(request["twist_deg"])*pi/180
        rotor=Rotor(request["hub_fraction"]*request["diameter_m"]/2,request["diameter_m"]/2,request["blades"])
    else
        a=request["airfoil"]; alpha=Float64.(a["alpha_deg"])*pi/180
        extended=[viterna(alpha,Float64.(a["cl"][i]),Float64.(a["cd"][i]),request["chord75_over_radius"]) for i in eachindex(a["reynolds"])]
        all(e[1] ≈ extended[1][1] for e in extended) || error("Inconsistent extended angle grids")
        af=AlphaReAF(extended[1][1],Float64.(a["reynolds"]),hcat([e[2] for e in extended]...),hcat([e[3] for e in extended]...))
        n=request["radial_stations"]
        radial=collect(range(.2+.4/n,1-.4/n,length=n))
        chord=request["root_chord_m"] .+ (request["tip_chord_m"]-request["root_chord_m"])*(radial.-.2)/.8
        twist=atan.(tan(request["reference_pitch_deg"]*pi/180)*.75 ./ radial)
        rotor=Rotor(.2*request["diameter_m"]/2,request["diameter_m"]/2,request["blades"],mach=PrandtlGlauert())
    end
    radius=radial*request["diameter_m"]/2
    rows=Dict{String,Any}[]
    for point in request["points"]
        row=Dict{String,Any}(point)
        try
            omega=point["rpm"]*pi/30
            sections=Section.(radius,chord,twist .+ point["collective_deg"]*pi/180,Ref(af))
            op=simple_op.(point["speed_m_s"],omega,radius,point["density_kg_m3"];mu=point["viscosity_pa_s"],asound=point["sound_speed_m_s"])
            out=solve.(Ref(rotor),sections,op)
            thrust,torque=thrusttorque(rotor,sections,out)
            power=torque*omega; n=point["rpm"]/60; d=request["diameter_m"]
            uninduced=sqrt.(point["speed_m_s"]^2 .+ (omega*radius).^2)
            reynolds=point["density_kg_m3"]*uninduced.*chord/point["viscosity_pa_s"]
            mach=uninduced/point["sound_speed_m_s"]
            tip_mach=hypot(point["speed_m_s"],omega*rotor.Rtip)/point["sound_speed_m_s"]
            alpha_deg=out.alpha*180/pi
            vals=[thrust,torque,power,out.Np...,out.Tp...,out.alpha...,out.W...]
            interior=(radius .> rotor.Rhub) .& (radius .< rotor.Rtip)
            all(isfinite,vals) && all(out.W[interior] .> 0) || error("Nonfinite or unsolved blade station")
            eta=thrust*point["speed_m_s"]/power
            valid=thrust>0 && power>0 && 0<=eta<=1
            reasons=String[]
            if !valid; push!(reasons,"nonpropulsive thrust/power/efficiency"); end
            if !official
                a=request["airfoil"]
                if minimum(alpha_deg)<minimum(a["alpha_deg"])-1e-8 || maximum(alpha_deg)>maximum(a["alpha_deg"])+1e-8
                    valid=false;push!(reasons,"accepted angle outside original XFOIL polar")
                end
                if minimum(reynolds)<minimum(a["reynolds"]) || maximum(reynolds)>maximum(a["reynolds"])
                    valid=false;push!(reasons,"Reynolds outside original XFOIL polar")
                end
                if max(maximum(mach),tip_mach)>.75
                    valid=false;push!(reasons,"local uninduced Mach exceeds 0.75")
                end
            end
            merge!(row,Dict("status"=>valid ? "valid" : "out_of_domain","diagnostics"=>reasons,
                "thrust_n"=>thrust,"torque_nm"=>torque,"shaft_power_w"=>power,"efficiency"=>eta,
                "ct"=>thrust/(point["density_kg_m3"]*n^2*d^4),"cq"=>torque/(point["density_kg_m3"]*n^2*d^5),
                "cp"=>power/(point["density_kg_m3"]*n^3*d^5),"advance_ratio"=>point["speed_m_s"]/(n*d),
                "radius_m"=>radius,"normal_load_n_m"=>collect(out.Np),"tangential_load_n_m"=>collect(out.Tp),
                "alpha_deg"=>collect(alpha_deg),"reynolds"=>reynolds,"mach"=>mach,"tip_mach"=>tip_mach,
                "section_cl"=>collect(out.cl),"section_cd"=>collect(out.cd)))
        catch exc
            merge!(row,Dict("status"=>"solver_failed","error"=>sprint(showerror,exc)))
        end
        push!(rows,row)
    end
    base=pkgdir(CCBlade)
    metadata=Dict("julia_version"=>string(VERSION),"ccblade_version"=>string(Base.pkgversion(CCBlade)),
        "package_sources"=>Dict(n=>bytes2hex(sha256(read(joinpath(base,n)))) for n in ["src/CCBlade.jl","src/airfoils.jl","Project.toml","LICENSE.md"]))
    open(output_path,"w") do io; TOML.print(io,Dict("metadata"=>metadata,"points"=>rows));end
    println("CCBlade points: ",length(rows)," valid: ",count(r->r["status"]=="valid",rows))
end
main(ARGS[1],ARGS[2])
