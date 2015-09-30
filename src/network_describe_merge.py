import os
import pandas as pd
import numpy as np
import networkx as nx
import matplotlib.pyplot as plt
import seaborn as sns
from pipelines.models import Project
import json


sns.set(style="whitegrid")


def name_to_repr(name):
    return "_".join([name.split("_")[0]] + [name.split("_")[2]] + name.split("_")[3:4])


def name_to_id(name):
    """This returns joined patient and sample IDs"""
    return "_".join([name.split("_")[2]] + name.split("_")[3:4])


def name_to_patient_id(name):
    return name.split("_")[2]


def name_to_sample_id(name):
    return name.split("_")[3]


def annotate_igvh_mutations(samples, clinical):
    new_samples = list()

    for sample in samples:
        if sample.cellLine == "CLL" and sample.technique == "ATAC-seq":
            _id = name_to_sample_id(sample.name)
            if clinical.loc[clinical['sample_id'] == _id, 'igvh_mutation_status'].tolist()[0] == 1:
                sample.mutated = True
            elif clinical.loc[clinical['sample_id'] == _id, 'igvh_mutation_status'].tolist()[0] == 2:
                sample.mutated = False
            else:
                sample.mutated = None
        else:
            sample.mutated = None
        new_samples.append(sample)
    return new_samples


def annotate_treatments(samples, clinical):
    """
    Annotate samples with timepoint, treatment_status, treatment_type
    """
    def string_to_date(string):
        if type(string) is str:
            if len(string) == 10:
                return pd.to_datetime(string, format="%d/%m/%Y")
            if len(string) == 7:
                return pd.to_datetime(string, format="%m/%Y")
            if len(string) == 4:
                return pd.to_datetime(string, format="%Y")
        return pd.NaT

    new_samples = list()

    for sample in samples:
        if sample.cellLine == "CLL":
            # get sample id
            sample_id = name_to_sample_id(sample.name)

            # get corresponding series from "clinical"
            sample_c = clinical[clinical['sample_id'] == sample_id].squeeze()

            # Get sample collection date
            sample.collection_date = string_to_date(sample_c['sample_collection_date'])
            # Get diagnosis date
            sample.diagnosis_date = string_to_date(sample_c['diagnosis_date'])
            # Get diagnosis disease
            sample.diagnosis_disease = sample_c['diagnosis_disease'] if type(sample_c['diagnosis_disease']) is str else None
            # Get time since diagnosis
            sample.time_since_diagnosis = sample.collection_date - sample.diagnosis_date

            # Get all treatment dates
            treatment_dates = [string_to_date(date) for date in sample_c[["treatment_%i_date" % (x) for x in range(1, 5)]].squeeze()]
            # Get treatment end date
            treatment_end_date = string_to_date(clinical[(clinical['sample_id'] == sample_id)][["treatment_end_date"]])
            # Check if there are earlier "timepoints"
            earlier_dates = [treatment_date for treatment_date in treatment_dates if treatment_date < sample.collection_date]

            # Annotate samples with active treatment
            for treatment_date in treatment_dates:
                # if one of the treatment dates is earlier
                if treatment_date < sample.collection_date:
                    # this sample was not collected at diagnosis time
                    sample.diagnosis_collection = False
                    # and no treatment end date in between, mark as under treatment
                    if treatment_end_date is pd.NaT:
                        sample.treatment_active = True
                    else:
                        if treatment_date < treatment_end_date < sample.collection_date:
                            sample.treatment_active = False
                        elif treatment_date < sample.collection_date < treatment_end_date:
                            sample.treatment_active = True
            # if there were no treatments before collection, consider untreated
            if not hasattr(sample, "treatment_active"):
                sample.treatment_active = False
                # if there were no treatments before collection, and collection was within 30 days of diagnosis, tag as collected at diagnosis
                if sample.time_since_diagnosis is not pd.NaT:
                    if abs(sample.time_since_diagnosis) < pd.to_timedelta(30, unit="days"):
                        sample.diagnosis_collection = True
            if not hasattr(sample, "diagnosis_collection"):
                sample.diagnosis_collection = False

            # Annotate treatment type, time since treatment
            if sample.treatment_active:
                if len(earlier_dates) > 0:
                    # Find out which earlier "timepoint" is closest and annotate treatment and response
                    previous_dates = [date for date in clinical[(clinical['sample_id'] == sample_id)][["treatment_%i_date" % (x) for x in range(1, 5)]].squeeze()]
                    closest_date = previous_dates[np.argmin([abs(date - sample.collection_date) for date in earlier_dates])]

                    # Annotate previous treatment date
                    sample.previous_treatment_date = string_to_date(closest_date)
                    # Annotate time since treatment
                    sample.time_since_treatment = sample.collection_date - string_to_date(closest_date)

                    # Get closest clinical "timepoint", annotate response
                    closest_timepoint = [tp for tp in range(1, 5) if closest_date == sample_c["treatment_%i_date" % tp]][0]

                    sample.treatment_type = sample_c['treatment_%i_regimen' % closest_timepoint]
                    sample.treatment_response = sample_c['treatment_%i_response' % closest_timepoint]

            # Annotate relapses
            # are there previous timepoints with good response?
            # Get previous clinical "timepoints", annotate response
            if len(earlier_dates) > 0:
                closest_timepoint = [tp for tp in range(1, 5) if closest_date == sample_c["treatment_%i_date" % tp]][0]

                # Annotate with previous known response
                sample.previous_response = sample_c['treatment_%i_response' % closest_timepoint]

                # if prior had bad response, mark current as relapse
                if sample_c['treatment_%i_response' % closest_timepoint] in ["CR", "GR"]:
                    sample.relapse = True
                else:
                    sample.relapse = False
            else:
                sample.relapse = False

        # If any attribute is not set, set to None
        for attr in ['diagnosis_collection', 'diagnosis_date', 'diagnosis_disease', 'time_since_treatment', 'treatment_type',
                     'treatment_response', "treatment_active", "previous_treatment_date", "previous_response", 'relapse']:
            if not hasattr(sample, attr):
                setattr(sample, attr, None)

        # Append sample
        new_samples.append(sample)
    return new_samples


def annotate_gender(samples, clinical):
    new_samples = list()

    for sample in samples:
        if sample.cellLine == "CLL" and sample.technique == "ATAC-seq":
            _id = name_to_sample_id(sample.name)
            if clinical.loc[clinical['sample_id'] == _id, 'patient_gender'].tolist()[0] == "F":
                sample.patient_gender = "F"
            elif clinical.loc[clinical['sample_id'] == _id, 'patient_gender'].tolist()[0] == "M":
                sample.patient_gender = "M"
            else:
                sample.patient_gender = None
        else:
            sample.patient_gender = None
        new_samples.append(sample)
    return new_samples


def annotate_mutations(samples, clinical):
    new_samples = list()

    for sample in samples:
        if sample.cellLine == "CLL" and sample.technique == "ATAC-seq":
            _id = name_to_sample_id(sample.name)
            sample.mutations = clinical[clinical['sample_id'] == _id]['mutations'].tolist()[0]
        else:
            sample.mutations = None
        new_samples.append(sample)
    return new_samples


def create_graph(network_file):
    # read in network file
    df = pd.read_csv(network_file, sep="\t")

    # create network
    G = nx.DiGraph()
    for i in df.index:
        G.add_edge(df.ix[i]['TF'], df.ix[i]['gene'], weight=df.ix[i]['interaction_score'])
    return G


def intersect_sum_weights(G1, G2):
    """
    Intersect two graphs, adding weights
    and keeping track of how many graphs
    have contributed to that edge's weight.
    """
    # the new graph
    G3 = nx.DiGraph()

    for u, v in G1.edges_iter():
        weight1 = G1[u][v]['weight']
        if (u, v) in G2.edges():
            weight2 = G2[u][v]['weight']
            # sum weights
            weight = weight2 + weight1

            # keep track of how many graphs have contributed to this edge's weight
            count = 0
            if "count" in G1[u][v].keys():
                count = G1[u][v]['count'] + count
            else:
                count = 1
            if "count" in G2[u][v].keys():
                count = G2[u][v]['count'] + count
            else:
                count = 2

            # add that value

            # add edge to new graph
            G3.add_edge(u, v, weight=weight, attr_dict={'count': count})
    return G3


def average_weights(G):
    """
    Averages the weight of each edge
    by the number of graphs which have
    contributed to the edge's weight
    (see intersect_sum_weights).
    """
    for u, v in G.edges_iter():
        weight = G[u][v]['weight']
        if 'count' in G[u][v].keys():
            weight /= G[u][v]['count']
        G.add_edge(u, v, weight=weight)
    return G


def describe_graph(G):
    """Graph description"""

    desc = list()
    # centrality
    # degree based
    desc.append(pd.Series(nx.degree_centrality(G), name="degree_centrality"))
    desc.append(pd.Series(nx.in_degree_centrality(G), name="in_degree_centrality"))
    desc.append(pd.Series(nx.out_degree_centrality(G), name="out_degree_centrality"))
    # closest-path based
    desc.append(pd.Series(nx.closeness_centrality(G), name="closeness_centrality"))
    desc.append(pd.Series(nx.betweenness_centrality(G), name="betweenness_centrality"))
    # eigenvector-based
    desc.append(pd.Series(nx.eigenvector_centrality(G), name="eigenvector_centrality"))
    desc.append(pd.Series(nx.katz_centrality_numpy(G), name="katz_centrality"))
    # load-based
    desc.append(pd.Series(nx.load_centrality(G), name="load_centrality"))

    # nx.dispersion(G)  # find un/coordinated nodes

    # average shortest path length
    # nx.average_shortest_path_length(G)

    # Connectivity
    # desc.append(pd.Series(nx.degree_assortativity_coefficient(G), name="degree_assortativity_coefficient"))
    # desc.append(pd.Series(nx.degree_pearson_correlation_coefficient(G), name="degree_pearson_correlation_coefficient"))
    # desc.append(pd.Series(nx.attribute_assortativity_coefficient(G, 'count'), name="attribute_assortativity_coefficient"))
    # desc.append(pd.Series(nx.numeric_assortativity_coefficient(G, 'count'), name="numeric_assortativity_coefficient"))

    desc.append(pd.Series(nx.average_neighbor_degree(G), name="average_neighbor_degree"))

    # desc.append(pd.Series(nx.average_degree_connectivity(G), name="average_degree_connectivity"))
    # desc.append(pd.Series(nx.k_nearest_neighbors(G), name="k_nearest_neighbors"))

    return pd.DataFrame(desc).T


# Get path configuration
data_dir = os.path.join('.', "data")
results_dir = os.path.join('.', "results")
plots_dir = os.path.join(results_dir, "plots")

# Get clinical info
clinical = pd.read_csv(os.path.join("metadata", "clinical_annotation.csv"))

# Start project
# prj = pickle.load(open("prj.pickle", 'rb'))
prj = Project("cll-patients")
prj.addSampleSheet("metadata/sequencing_sample_annotation.csv")

# Annotate with clinical data
prj.samples = annotate_igvh_mutations(prj.samples, clinical)
prj.samples = annotate_treatments(prj.samples, clinical)
prj.samples = annotate_mutations(prj.samples, clinical)
prj.samples = annotate_gender(prj.samples, clinical)

# Start analysis object
# only with ATAC-seq samples that passed QC
samples_to_exclude = [
    'CLL_ATAC-seq_4851_1-5-45960_ATAC29-6_hg19',
    'CLL_ATAC-seq_5186_1-5-57350_ATAC17-4_hg19',
    'CLL_ATAC-seq_4784_1-5-52817_ATAC17-6_hg19',
    'CLL_ATAC-seq_981_1-5-42480_ATAC16-6_hg19',
    'CLL_ATAC-seq_5277_1-5-57269_ATAC17-8_hg19',
    'CLL_ATAC-seq_4621_1-5-36904_ATAC16-2_hg19',
    'CLL_ATAC-seq_5147_1-5-48105_ATAC17-2_hg19',
    'CLL_ATAC-seq_4621_1-5-36904_ATAC16-2_hg19']
samples = [sample for sample in prj.samples if sample.cellLine == "CLL" and sample.technique == "ATAC-seq" and sample.name not in samples_to_exclude]


for i, sample in enumerate(samples):
    print(sample)
    # Create sample graph
    graph_file = os.path.join(data_dir, "footprints", sample.name + ".piq.TF-TF_interactions.tsv")
    G = create_graph(graph_file)

    # Describe network
    df = describe_graph(G)
    df["sample"] = sample.name
    if i == 0:
        desc = df
    else:
        desc = desc.append(df)

    # Intersect graphs, keeping weight from each
    if i == 0:
        master_graph = G
    else:
        master_graph = intersect_sum_weights(master_graph, G)

G = average_weights(master_graph)

# write network to disk
# this can be visualized with D3.js (e.g. http://bl.ocks.org/mbostock/4062045#index.html)
json_data = nx.readwrite.json_graph.node_link_data(G)
with open("/home/afr/data.json", "w") as handle:
    json.dump(json_data, handle)


# Drawing
# with edge weights as colormap
nx.draw_networkx(
    G, pos=nx.spring_layout(G), alpha=.5,
    arrows=False,
    #edge_color=[G[u][v]['weight'] for u, v in G.edges()],
    edge_cmap=plt.get_cmap('gray_r')  # white to gray
)

# Plot network description
# rank vs value for all samples, in a grid of variables
desc['TF'] = desc.index
df = pd.melt(desc, id_vars=['TF', 'sample'])
ranks = desc.rank(numeric_only=True)
ranks['TF'] = ranks.index
ranks = pd.melt(ranks, id_vars=['TF'], value_name='rank')
# merge values and ranks
value_ranks = pd.merge(df, ranks)

g = sns.FacetGrid(value_ranks, hue="sample", col="variable", col_wrap=3, margin_titles=True, size=4)
g.map(plt.scatter, "rank", "value", color="#338844", edgecolor="white", s=50, lw=1)

# mean vs -std across samples, in a grid of variables
df.groupby(["TF", "variable"]).apply(np.mean)
df.groupby(["TF", "variable"]).apply(np.std)


g = sns.FacetGrid(value_ranks, col="variable", col_wrap=3, margin_titles=True, size=4)
g.map(plt.scatter, "mean", "std", color="#338844", edgecolor="white", s=50, lw=1)


#


# Describe networks
# classify nodes into regulator/regulated
# color in visualization

# Compare Networks
